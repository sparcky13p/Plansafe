"""Apply confirmed contractor instructions to the rule-based requirements.

Order: input overrides change the rule inputs (rules are re-run with them),
then substitutions, exclusions and additions change the required quantities,
then stock on hand reduces what has to be bought.

Safety guard: nothing silently drops below what the rules require. A line
whose required quantity ends up under its rule minimum (other than through an
approved equivalent substitution) is flagged `below_minimum`, and an
exclusion without a reason is rejected.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from safetyplan.instructions.schema import (
    GUARDRAIL_ITEMS,
    GUARDRAIL_SYSTEM,
    AddItem,
    BrandPref,
    BudgetCap,
    Exclude,
    InputOverride,
    InventoryOnHand,
    ParsedInstructions,
    Substitute,
)
from safetyplan.rules.engine import ProjectInputs, RequirementsResult, generic_items

# (from, to) -> to-units per from-unit. Approved because the code allows the
# alternative, e.g. OSHA 1926.501(b)(1): guardrail, safety net OR personal fall arrest.
EQUIVALENTS = {
    (GUARDRAIL_SYSTEM, "safety_net_m2"): (2.5, "29 CFR 1926.501(b)(1) allows safety net systems in place of guardrails"),
}


@dataclass
class PlanLine:
    item: str
    name: str
    unit: str
    category: str
    rule_min: float  # what the rules require (0 for contractor additions)
    required: float  # after substitutions / exclusions / additions
    on_hand: float = 0.0
    to_buy: float = 0.0
    below_minimum: bool = False
    verified: bool = True
    flags: list[str] = field(default_factory=list)
    instructions: list[int] = field(default_factory=list)  # instruction numbers that touched this line


@dataclass
class Applied:
    n: int
    kind: str
    quote: str
    effect: str


@dataclass
class PurchasePlan:
    lines: list[PlanLine]
    applied: list[Applied]
    rejected: list[Applied]
    notes: list[str]
    brand_pref: list[str]
    budget: float | None

    @property
    def needs(self) -> dict[str, float]:
        return {l.item: l.to_buy for l in self.lines if l.to_buy > 0}

    def to_dict(self) -> dict:
        return {
            "lines": [asdict(l) for l in self.lines],
            "applied": [asdict(a) for a in self.applied],
            "rejected": [asdict(a) for a in self.rejected],
            "notes": self.notes,
            "brand_pref": self.brand_pref,
            "budget": self.budget,
            "below_minimum": [l.item for l in self.lines if l.below_minimum],
        }


def apply_input_overrides(inputs: ProjectInputs, parsed: ParsedInstructions) -> tuple[ProjectInputs, list[Applied]]:
    data = inputs.model_dump()
    applied = []
    for ins in parsed.instructions:
        if isinstance(ins, InputOverride):
            old = data.get(ins.field)
            new = ins.value if ins.field in ("floor_height", "spare") else int(round(ins.value))
            data[ins.field] = new
            applied.append(Applied(ins.n, ins.kind, ins.quote, f"{ins.field}: {old} -> {new}"))
    if any(a.effect.startswith("workforce") for a in applied) and inputs.workers_at_height == math.ceil(
            inputs.workforce * 0.4) and not any(a.effect.startswith("workers_at_height") for a in applied):
        data["workers_at_height"] = None  # recompute the 40% default from the new workforce
    return ProjectInputs.model_validate(data), applied


def apply_instructions(result: RequirementsResult, parsed: ParsedInstructions,
                       pre_applied: list[Applied] | None = None) -> PurchasePlan:
    items = generic_items()
    applied: list[Applied] = list(pre_applied or [])
    rejected: list[Applied] = []

    # Raw (unrounded) required quantity per item, from governing trace entries.
    raw: dict[str, float] = {}
    lines: dict[str, PlanLine] = {}
    for r in result.requirements:
        raw[r.item] = sum(t.qty for t in r.trace if t.governing)
        lines[r.item] = PlanLine(r.item, r.name, r.unit, r.category, r.qty, r.qty, verified=r.verified)
    traces = {r.item: r.trace for r in result.requirements}
    approved_reduction: set[str] = set()

    def line(item: str) -> PlanLine:
        if item not in lines:
            m = items[item]
            lines[item] = PlanLine(item, m["name"], m["unit"], m["category"], 0.0, 0.0)
            raw[item] = 0.0
        return lines[item]

    for ins in parsed.instructions:
        if isinstance(ins, Substitute):
            from_items = list(GUARDRAIL_ITEMS) if ins.from_item == GUARDRAIL_SYSTEM else [ins.from_item]
            basis = "guardrail_top_rail_m" if ins.from_item == GUARDRAIL_SYSTEM else ins.from_item
            eq = EQUIVALENTS.get((ins.from_item, ins.to_item))
            ratio = ins.ratio or (eq[0] if eq else 1.0)
            moved_basis = 0.0
            touched = []
            for it in from_items:
                for t in traces.get(it, []):
                    if not t.governing or (ins.faces and t.facing not in ins.faces):
                        continue
                    if ins.faces and t.feature_type not in ("slab_edge", "balcony"):
                        continue
                    raw[it] -= t.qty
                    if it == basis:
                        moved_basis += t.qty
                    touched.append(it)
            if moved_basis <= 0:
                rejected.append(Applied(ins.n, ins.kind, ins.quote,
                                        "nothing to replace" + (f" on the {'/'.join(ins.faces)} side" if ins.faces else "")))
                continue
            add = moved_basis * ratio
            to = line(ins.to_item)
            raw[ins.to_item] += add
            to.instructions.append(ins.n)
            to.flags.append(f"+{add:g} {to.unit} replacing {moved_basis:g} m of {ins.from_item.replace('_', ' ')} (#{ins.n})")
            for it in dict.fromkeys(touched):
                l = lines[it]
                l.instructions.append(ins.n)
                if eq:
                    approved_reduction.add(it)
                    l.flags.append(f"partly replaced by {ins.to_item} (#{ins.n}): {eq[1]}")
                else:
                    l.flags.append(f"replaced by {ins.to_item} (#{ins.n}) - not an approved equivalent")
            where = f" on the {'/'.join(ins.faces)} side" if ins.faces else ""
            applied.append(Applied(ins.n, ins.kind, ins.quote,
                                   f"{moved_basis:g} m of {ins.from_item.replace('_', ' ')}{where} -> {add:g} {to.unit} of {ins.to_item}"))

        elif isinstance(ins, Exclude):
            if not ins.reason.strip():
                rejected.append(Applied(ins.n, ins.kind, ins.quote,
                                        "a reason is required to remove a safety item"))
                continue
            l = line(ins.item)
            raw[ins.item] = 0.0
            l.instructions.append(ins.n)
            l.flags.append(f"removed by contractor (#{ins.n}): {ins.reason}")
            applied.append(Applied(ins.n, ins.kind, ins.quote, f"{ins.item} removed ({ins.reason})"))

        elif isinstance(ins, AddItem):
            l = line(ins.item)
            raw[ins.item] += ins.qty
            l.instructions.append(ins.n)
            l.flags.append(f"+{ins.qty:g} added by contractor (#{ins.n})")
            applied.append(Applied(ins.n, ins.kind, ins.quote, f"+{ins.qty:g} {ins.item}"))

    for it, l in lines.items():
        l.required = float(max(0, math.ceil(round(raw[it], 6))))

    for ins in parsed.instructions:
        if isinstance(ins, InventoryOnHand):
            l = line(ins.item)
            l.on_hand += ins.qty
            l.instructions.append(ins.n)
            applied.append(Applied(ins.n, ins.kind, ins.quote, f"{ins.qty:g} {ins.item} already on site"))

    for l in lines.values():
        l.to_buy = max(0.0, l.required - l.on_hand)
        if l.required < l.rule_min and l.item not in approved_reduction:
            l.below_minimum = True
            l.flags.append(f"BELOW RULE MINIMUM: rules require {l.rule_min:g}, plan has {l.required:g}")

    brands = [b for ins in parsed.instructions if isinstance(ins, BrandPref) for b in ins.brands]
    budgets = [ins.amount_inr for ins in parsed.instructions if isinstance(ins, BudgetCap)]
    for ins in parsed.instructions:
        if isinstance(ins, BrandPref):
            applied.append(Applied(ins.n, ins.kind, ins.quote, f"prefer {', '.join(ins.brands)}"))
        elif isinstance(ins, BudgetCap):
            applied.append(Applied(ins.n, ins.kind, ins.quote, f"budget Rs {ins.amount_inr:,.0f}"))

    order = list(items)
    cats = list(dict.fromkeys(m["category"] for m in items.values()))
    ordered = sorted(lines.values(), key=lambda l: (cats.index(l.category), order.index(l.item)))
    applied.sort(key=lambda a: a.n)
    return PurchasePlan(ordered, applied, rejected, list(parsed.notes), brands, budgets[-1] if budgets else None)
