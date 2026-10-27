import json

import pytest

from safetyplan.detect.muse import MockMuse
from safetyplan.instructions.apply import apply_input_overrides, apply_instructions
from safetyplan.instructions.parse import parse_instructions, parse_offline
from safetyplan.instructions.schema import ParsedInstructions
from safetyplan.rules.engine import ProjectInputs, evaluate_rules
from safetyplan.rules.features import Feature

# (text, kind, fields that must match)
PHRASES = [
    ("We already have 25 helmets", "inventory_on_hand", {"item": "helmet", "qty": 25}),
    ("humare paas 30 safety shoes pehle se hai", "inventory_on_hand", {"item": "safety_shoes", "qty": 30}),
    ("10 harness already available on site", "inventory_on_hand", {"item": "full_body_harness", "qty": 10}),
    ("Use safety nets instead of guardrails on the north face", "substitute",
     {"from_item": "guardrail_system", "to_item": "safety_net_m2", "faces": ["north"]}),
    ("north aur east side pe railing ki jagah jaali lagana", "substitute",
     {"from_item": "guardrail_system", "to_item": "safety_net_m2", "faces": ["north", "east"]}),
    ("add 15% spares", "input_override", {"field": "spare", "value": 0.15}),
    ("15% extra rakhna", "input_override", {"field": "spare", "value": 0.15}),
    ("work only on 3 floors at a time", "input_override", {"field": "floors_concurrent", "value": 3}),
    ("3 floor ek saath chalega", "input_override", {"field": "floors_concurrent", "value": 3}),
    ("total 60 workers on site", "input_override", {"field": "workforce", "value": 60}),
    ("site par 45 mazdoor honge", "input_override", {"field": "workforce", "value": 45}),
    ("12 workers at height", "input_override", {"field": "workers_at_height", "value": 12}),
    ("prefer SafeCrest brand", "brand_pref", {"brands": ["SafeCrest"]}),
    ("budget under Rs. 2 lakh", "budget_cap", {"amount_inr": 200000}),
    ("budget 2,50,000", "budget_cap", {"amount_inr": 250000}),
    ("harness nahi chahiye", "exclude", {"item": "full_body_harness", "reason": ""}),
    ("no lifeline because we use guardrails everywhere", "exclude",
     {"item": "lifeline_m", "reason": "we use guardrails everywhere"}),
    ("add 10 extra gloves", "add_item", {"item": "gloves_pair", "qty": 10}),
]


@pytest.mark.parametrize("text,kind,fields", PHRASES, ids=[p[0] for p in PHRASES])
def test_offline_parser(text, kind, fields):
    p = parse_offline(text)
    assert len(p.instructions) == 1, (p.instructions, p.notes)
    ins = p.instructions[0].model_dump()
    assert ins["kind"] == kind
    for k, v in fields.items():
        assert ins[k] == v, f"{k}: {ins[k]!r} != {v!r}"
    assert ins["quote"] and ins["n"] == 1


def test_multi_clause_text_numbered_and_notes_kept():
    p = parse_offline("prefer SafeCrest brand, budget under Rs. 2 lakh\nThe site is near a school.\nadd 10% spare")
    assert [i.kind for i in p.instructions] == ["brand_pref", "budget_cap", "input_override"]
    assert [i.n for i in p.instructions] == [1, 2, 3]
    assert p.notes == ["The site is near a school"]


def test_model_parser_via_mock_matches_offline():
    text = "We already have 25 helmets; 15% extra rakhna"
    p = parse_instructions(text, MockMuse())
    assert p.parser == "mock"
    assert [i.kind for i in p.instructions] == ["inventory_on_hand", "input_override"]


def test_model_unknown_item_becomes_note():
    reply = json.dumps({"instructions": [{"kind": "add_item", "item": "jetpack", "qty": 2, "quote": "2 jetpacks"}],
                        "notes": []})
    p = parse_instructions("2 jetpacks", MockMuse(replies=[reply]))
    assert not p.instructions and "jetpack" in p.notes[0]


def test_model_failure_falls_back_to_offline():
    p = parse_instructions("We already have 25 helmets", MockMuse(replies=["nope", "still nope"]))
    assert p.parser == "offline" and p.instructions[0].kind == "inventory_on_hand"
    assert "unavailable" in p.warnings[0]


# --- applying ------------------------------------------------------------------

FEATS = [
    Feature("E1", "slab_edge", length=20.0, max_dim=20.0, edge_ids=["E1"], facing="north"),
    Feature("E2", "slab_edge", length=10.0, max_dim=10.0, edge_ids=["E2"], facing="east"),
]
INPUTS = ProjectInputs(floors=4, floor_height=3.0, workforce=40, floors_concurrent=2, packs=["osha_1926", "is_bocw"])


def run(text, inputs=INPUTS):
    parsed = parse_offline(text)
    eff, pre = apply_input_overrides(inputs, parsed)
    return apply_instructions(evaluate_rules(FEATS, eff), parsed, pre)


def lines(plan):
    return {l.item: l for l in plan.lines}


def test_inventory_reduces_purchase_not_requirement():
    l = lines(run("We already have 25 helmets"))["helmet"]
    assert (l.rule_min, l.required, l.on_hand, l.to_buy, l.below_minimum) == (44, 44, 25, 19, False)


def test_inventory_larger_than_need_buys_nothing():
    l = lines(run("We already have 100 helmets"))["helmet"]
    assert l.to_buy == 0 and not l.below_minimum


def test_exclude_without_reason_rejected():
    plan = run("harness nahi chahiye")
    assert lines(plan)["full_body_harness"].required == 18
    assert plan.rejected[0].effect == "a reason is required to remove a safety item"


def test_exclude_with_reason_is_flagged_below_minimum():
    plan = run("no harness because all edges have guardrails")
    l = lines(plan)["full_body_harness"]
    assert l.required == 0 and l.below_minimum
    assert any("BELOW RULE MINIMUM" in f for f in l.flags)
    assert "full_body_harness" in plan.to_dict()["below_minimum"]


def test_approved_substitution_on_one_face_only():
    plan = run("Use safety nets instead of guardrails on the north face")
    ls = lines(plan)
    # north edge 20 m * 2 floors = 40 m moved; east 10 m * 2 = 20 m stays.
    assert ls["guardrail_top_rail_m"].required == 20 and not ls["guardrail_top_rail_m"].below_minimum
    assert ls["guardrail_post"].required == 12  # (ceil(10/2.4)+1)*2 for the east edge only
    assert ls["safety_net_m2"].required == 175  # BOCW net 30*2.5 = 75 + 40*2.5 = 100
    assert ls["safety_net_m2"].rule_min == 75
    assert plan.applied[0].n == 1 and "north" in plan.applied[0].effect


def test_non_equivalent_substitution_is_flagged():
    plan = run("use signs instead of railings")
    l = lines(plan)["guardrail_top_rail_m"]
    assert l.below_minimum and any("not an approved equivalent" in f for f in l.flags)


def test_substitution_with_nothing_to_replace_is_rejected():
    plan = run("Use safety nets instead of guardrails on the south face")
    assert plan.rejected and "nothing to replace" in plan.rejected[0].effect


def test_add_item_creates_line_without_minimum():
    l = lines(run("add 10 extra gloves"))["gloves_pair"]
    assert (l.rule_min, l.required, l.below_minimum) == (0, 10, False)


def test_input_override_reruns_rules():
    ls = lines(run("work only on 3 floors at a time"))
    assert ls["guardrail_top_rail_m"].rule_min == 90  # 30 m * 3 floors


def test_workforce_override_recomputes_default_at_height():
    ls = lines(run("total 60 workers on site"))
    assert ls["helmet"].rule_min == 66  # 60 * 1.1
    assert ls["full_body_harness"].rule_min == 27  # ceil(60*0.4)=24 * 1.1 -> 27


def test_brand_and_budget_passed_through():
    plan = run("prefer SafeCrest brand, budget under Rs. 2 lakh")
    assert plan.brand_pref == ["SafeCrest"] and plan.budget == 200000


def test_needs_only_positive_to_buy():
    plan = run("We already have 100 helmets")
    assert "helmet" not in plan.needs and plan.needs["guardrail_top_rail_m"] == 60


def test_empty_instructions_change_nothing():
    plan = apply_instructions(evaluate_rules(FEATS, INPUTS), ParsedInstructions())
    assert all(l.required == l.rule_min == l.to_buy for l in plan.lines)
    assert not plan.applied and not plan.rejected
