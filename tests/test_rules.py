from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from safetyplan.detect.muse import MockMuse
from safetyplan.detect.pipeline import detect
from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf
from safetyplan.ingest.render import render_png
from safetyplan.rules.engine import DEFAULT_PACKS, ProjectInputs, Rule, evaluate_rules, load_pack
from safetyplan.rules.expr import ExprError, evaluate
from safetyplan.rules.features import Feature, build_features

CASES = yaml.safe_load((Path(__file__).parent / "rules_cases.yaml").read_text())


def qtys(result):
    return {r.item: r.qty for r in result.requirements}


class TestExpr:
    def test_arithmetic_and_functions(self):
        assert evaluate("(ceil(length / 2.4) + 1) * n", {"length": 10, "n": 2}) == 12

    def test_ternary_and_boolean(self):
        env = {"a": 0.7, "f": 4}
        assert evaluate("f if a + 0.3 <= 1.0 else 0", env) == 4
        assert evaluate("a > 0.5 and not a > 1", env) is True

    @pytest.mark.parametrize(
        "src", ["__import__('os')", "a.b", "open('x')", "[1,2]", "'text'", "lambda: 1", "ceil(x=1)"]
    )
    def test_rejects_unsafe(self, src):
        with pytest.raises(ExprError):
            evaluate(src, {"a": 1})

    def test_unknown_variable(self):
        with pytest.raises(ExprError, match="unknown variable"):
            evaluate("nope + 1", {})


class TestRulePacks:
    @pytest.mark.parametrize("pack", DEFAULT_PACKS)
    def test_packs_load_and_validate(self, pack):
        p = load_pack(pack)
        assert p.rules and len({r.id for r in p.rules}) == len(p.rules)

    def test_osha_rules_verified_indian_rules_flagged(self):
        assert all(r.verified for r in load_pack("osha_1926").rules)
        assert not any(r.verified for r in load_pack("is_bocw").rules)

    def test_rule_with_unknown_variable_rejected(self):
        with pytest.raises(ValidationError, match="unknown variable"):
            Rule(id="X", title="x", applies_to=["slab_edge"], when="height > 2", citation="c",
                 summary="s", produces=[{"item": "helmet", "qty": "1"}])

    def test_project_rule_cannot_use_feature_vars(self):
        with pytest.raises(ValidationError):
            Rule(id="X", title="x", applies_to=["project"], citation="c", summary="s",
                 produces=[{"item": "helmet", "qty": "length"}])

    def test_unknown_pack(self):
        with pytest.raises(ValueError):
            load_pack("nope")


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_rule_case(case):
    inputs = {**CASES["defaults"]["inputs"], **case.get("inputs", {}), "packs": case["packs"]}
    feats = [Feature(**f) for f in case["features"]]
    got = qtys(evaluate_rules(feats, ProjectInputs(**inputs)))
    for item, q in case.get("expect", {}).items():
        assert got.get(item) == q, f"{item}: got {got.get(item)}, expected {q}"
    for item in case.get("absent", []):
        assert item not in got, f"{item} should be absent, got {got[item]}"


class TestInputs:
    def test_workers_at_height_defaults_to_40_percent(self):
        assert ProjectInputs(floors=3, floor_height=3, workforce=25).workers_at_height == 10

    def test_active_floors_capped_by_floors(self):
        assert ProjectInputs(floors=1, floor_height=3, workforce=1, floors_concurrent=3).active_floors == 1

    @pytest.mark.parametrize("bad", [{"floors": 0}, {"floor_height": 0}, {"workforce": -1}, {"spare": 2}])
    def test_validation(self, bad):
        with pytest.raises(ValidationError):
            ProjectInputs(**{"floors": 2, "floor_height": 3, "workforce": 10, **bad})


@pytest.fixture(scope="module")
def tower(fixtures):
    raw = load_dxf(fixtures["tower_mm.dxf"])
    geom = build_geometry(raw)
    dets = detect(geom, render_png(raw, geom), MockMuse()).detections
    return geom, dets


TOWER_INPUTS = ProjectInputs(floors=4, floor_height=3.0, workforce=40, floors_concurrent=2)


class TestTowerGolden:
    """Whole pipeline on the fixture; quantities checked by hand in the comments."""

    def test_features(self, tower):
        geom, dets = tower
        feats = {f.id: f for f in build_features(geom, dets)}
        bal = next(f for f in feats.values() if f.type == "balcony")
        assert bal.length == pytest.approx(6.4) and len(bal.edge_ids) == 3
        edges = [f for f in feats.values() if f.type == "slab_edge"]
        assert sum(f.length for f in edges) == pytest.approx(66.0)  # 72.4 outline - 6.4 balcony

    def test_quantities(self, tower):
        geom, dets = tower
        got = qtys(evaluate_rules(build_features(geom, dets), TOWER_INPUTS))
        assert got == {
            # edges 72.4*2 = 144.8, lift 10*2 = 20, stair (15.4-2.7)*2 = 25.4 -> 190.2
            "guardrail_top_rail_m": 191, "guardrail_mid_rail_m": 191, "toe_board_m": 191,
            # edges (5+8+10+8+5 + balcony 4)*2 = 80, lift 6*2 = 12, stair 7*2 = 14
            "guardrail_post": 106,
            "stair_handrail_m": 40,  # 2 flights * 5.0 m * 4 floors
            "lift_landing_barrier": 4,
            "hole_cover_1m": 4,  # duct 0.6 m
            "hole_cover_1_5m": 4,  # cut-out 1.0 m
            "safety_net_m2": 181,  # 72.4 * 2.5
            "full_body_harness": 18, "lanyard_double": 18,  # 16 at height * 1.1
            "lifeline_m": 73, "anchor_point": 9,
            "helmet": 44, "safety_shoes": 44, "reflective_vest": 44, "gloves_pair": 44,
            "danger_sign": 24,  # (8 + 4 openings) * 2
            "first_aid_box": 1,
        }

    def test_protected_edge_and_relabel(self, tower):
        geom, dets = tower
        cut = next(c.id for c in geom.candidates if "OPENING_CUTOUT" in c.blocks)
        feats = build_features(geom, dets, type_overrides={cut: "other"}, protected_edges={"E7"})
        got = qtys(evaluate_rules(feats, TOWER_INPUTS))
        assert got["guardrail_top_rail_m"] == 151  # 190.2 - 20 m edge * 2 floors
        assert "hole_cover_1_5m" not in got

    def test_trace_points_to_rules_and_drawing(self, tower):
        geom, dets = tower
        res = evaluate_rules(build_features(geom, dets), TOWER_INPUTS)
        rail = next(r for r in res.requirements if r.item == "guardrail_top_rail_m")
        e3 = [t for t in rail.trace if t.feature_id == "E7"]
        assert {t.pack for t in e3} == {"osha_1926", "is_bocw"}
        gov = [t for t in e3 if t.governing]
        assert len(gov) == 1 and gov[0].rule_id == "OSHA-EDGE-GUARDRAIL"  # verified wins ties
        assert gov[0].inputs == {"active_floors": 2, "length": 20.0} and gov[0].qty == 40
        assert gov[0].edge_ids == ["E7"]
        assert rail.verified

    def test_unverified_lines_flagged(self, tower):
        geom, dets = tower
        res = evaluate_rules(build_features(geom, dets), TOWER_INPUTS)
        flags = {r.item: r.verified for r in res.requirements}
        assert flags["helmet"] and not flags["safety_net_m2"] and not flags["first_aid_box"]

    def test_serialises(self, tower):
        geom, dets = tower
        d = evaluate_rules(build_features(geom, dets), TOWER_INPUTS).to_dict()
        assert d["inputs"]["derived"]["exposed_edge_length"] == pytest.approx(72.4)
        assert all("trace" in r and "verified" in r for r in d["requirements"])
