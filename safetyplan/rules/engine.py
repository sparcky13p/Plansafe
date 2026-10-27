"""Rules engine: confirmed features + project inputs -> equipment requirements.

Each requirement line carries a trace back to the rules and drawing features
that produced it. When several packs require the same thing (same `group`,
feature and item), the largest quantity governs instead of being summed.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from safetyplan.rules.expr import evaluate, names
from safetyplan.rules.features import Feature

LIBRARY = Path(__file__).parent / "library"
GENERIC_ITEMS = Path(__file__).parents[1] / "catalog" / "generic_items.yaml"
DEFAULT_PACKS = ("osha_1926", "is_bocw", "site_practice")

FEATURE_VARS = {"length", "perimeter", "area", "min_dim", "max_dim"}
PROJECT_VARS = {
    "floors", "floor_height", "top_height", "active_floors", "workforce", "workers_at_height",
    "spare", "exposed_edge_length", "opening_count", "max_cover_span", "post_spacing",
}


# --- Inputs ------------------------------------------------------------------


class ProjectInputs(BaseModel):
    floors: int = Field(ge=1, description="suspended floors/slabs to be built above ground")
    floor_height: float = Field(gt=0, le=10, description="floor-to-floor height, m")
    workforce: int = Field(ge=0)
    workers_at_height: int | None = Field(None, ge=0, description="default 40% of workforce")
    floors_concurrent: int = Field(2, ge=1, description="floors with open edges at the same time")
    spare: float = Field(0.1, ge=0, le=1, description="spare factor for PPE")
    packs: list[str] = Field(default_factory=lambda: list(DEFAULT_PACKS))
    max_cover_span: float = Field(1.5, gt=0, description="largest opening closed with a cover plate, m")
    post_spacing: float = Field(2.4, gt=0, description="max guardrail post spacing, m (8 ft)")

    @model_validator(mode="after")
    def _defaults(self):
        if self.workers_at_height is None:
            self.workers_at_height = math.ceil(self.workforce * 0.4)
        return self

    @property
    def active_floors(self) -> int:
        return min(self.floors_concurrent, self.floors)


# --- Rule pack schema --------------------------------------------------------


class Produce(BaseModel):
    item: str
    qty: str


class Rule(BaseModel):
    id: str
    title: str
    group: str | None = None
    applies_to: list[str]
    when: str = "True"
    citation: str
    summary: str
    produces: list[Produce]
    verified: bool = False

    @model_validator(mode="after")
    def _check_vars(self):
        allowed = PROJECT_VARS | ({"True", "False"})
        if "project" not in self.applies_to:
            allowed |= FEATURE_VARS
        for src in [self.when, *(p.qty for p in self.produces)]:
            unknown = names(src) - allowed
            if unknown:
                raise ValueError(f"rule {self.id}: unknown variable(s) {sorted(unknown)} in {src!r}")
        return self


class RulePack(BaseModel):
    pack: str
    title: str
    version: int
    rules: list[Rule]


@lru_cache(maxsize=None)
def load_pack(pack_id: str) -> RulePack:
    path = LIBRARY / f"{pack_id}.yaml"
    if not path.exists():
        raise ValueError(f"unknown rule pack {pack_id!r}")
    pack = RulePack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    items = generic_items()
    for r in pack.rules:
        for p in r.produces:
            if p.item not in items:
                raise ValueError(f"rule {r.id}: unknown item {p.item!r}")
    return pack


@lru_cache(maxsize=None)
def generic_items() -> dict[str, dict]:
    return yaml.safe_load(GENERIC_ITEMS.read_text(encoding="utf-8"))["items"]


# --- Output ------------------------------------------------------------------


@dataclass
class TraceEntry:
    rule_id: str
    pack: str
    citation: str
    summary: str
    verified: bool
    feature_id: str  # "PROJECT" for project-level rules
    feature_type: str
    edge_ids: list[str]
    formula: str
    inputs: dict[str, float]
    qty: float
    governing: bool = True  # False when another pack's rule required more
    facing: str = ""


@dataclass
class Requirement:
    item: str
    name: str
    unit: str
    category: str
    qty: float
    min_spec: list[str]
    trace: list[TraceEntry] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return all(t.verified for t in self.trace if t.governing)


@dataclass
class SkippedRule:
    rule_id: str
    feature_id: str
    reason: str


@dataclass
class RequirementsResult:
    requirements: list[Requirement]
    skipped: list[SkippedRule]
    inputs: dict

    def to_dict(self) -> dict:
        return {
            "inputs": self.inputs,
            "requirements": [{**asdict(r), "verified": r.verified} for r in self.requirements],
            "skipped": [asdict(s) for s in self.skipped],
        }


# --- Engine ------------------------------------------------------------------


def evaluate_rules(features: list[Feature], inp: ProjectInputs) -> RequirementsResult:
    edge_like = [f for f in features if f.type in ("slab_edge", "balcony")]
    openings = [f for f in features if f.type not in ("slab_edge", "balcony")]
    project_env = {
        "floors": inp.floors,
        "floor_height": inp.floor_height,
        "top_height": inp.floors * inp.floor_height,
        "active_floors": inp.active_floors,
        "workforce": inp.workforce,
        "workers_at_height": inp.workers_at_height,
        "spare": inp.spare,
        "exposed_edge_length": round(sum(f.length for f in edge_like), 3),
        "opening_count": len(openings),
        "max_cover_span": inp.max_cover_span,
        "post_spacing": inp.post_spacing,
    }
    project = Feature("PROJECT", "project")

    # (group, feature, item) -> candidate trace entries from different rules/packs
    slots: dict[tuple[str, str, str], list[TraceEntry]] = {}
    skipped: list[SkippedRule] = []

    for pack_id in inp.packs:
        pack = load_pack(pack_id)
        for rule in pack.rules:
            targets = [project] if "project" in rule.applies_to else [
                f for f in features if f.type in rule.applies_to
            ]
            for f in targets:
                env = {**project_env, **(f.vars() if f is not project else {})}
                if not evaluate(rule.when, env):
                    skipped.append(SkippedRule(rule.id, f.id, f"condition not met: {rule.when}"))
                    continue
                for p in rule.produces:
                    qty = float(evaluate(p.qty, env))
                    if qty <= 0:
                        continue
                    used = {k: env[k] for k in sorted(names(p.qty))}
                    entry = TraceEntry(
                        rule.id, pack.pack, rule.citation, rule.summary.strip(), rule.verified,
                        f.id, f.type, list(f.edge_ids), p.qty, used, round(qty, 3), facing=f.facing,
                    )
                    key = (rule.group or rule.id, f.id, p.item)
                    slots.setdefault(key, []).append(entry)

    items = generic_items()
    totals: dict[str, Requirement] = {}
    for (_, _, item), entries in slots.items():
        top = max(entries, key=lambda e: (e.qty, e.verified))
        for e in entries:
            e.governing = e is top
        meta = items[item]
        req = totals.setdefault(
            item,
            Requirement(item, meta["name"], meta["unit"], meta["category"], 0.0, list(meta.get("min_spec", []))),
        )
        req.qty += top.qty
        req.trace.extend(entries)

    for r in totals.values():
        r.qty = _round_up(r.qty)

    order = list(items)
    cats = list(dict.fromkeys(m["category"] for m in items.values()))
    reqs = sorted(totals.values(), key=lambda r: (cats.index(r.category), order.index(r.item)))
    return RequirementsResult(reqs, skipped, {**inp.model_dump(), "derived": project_env})


def _round_up(q: float) -> float:
    # Whole units for everything; tolerate float noise like 144.80000000000001.
    return float(math.ceil(round(q, 6)))
