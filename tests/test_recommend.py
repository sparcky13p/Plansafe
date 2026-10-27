import pytest

from safetyplan.catalog.demo import demo_suppliers
from safetyplan.catalog.model import SKU, Supplier
from safetyplan.sku import recommend as rec_mod
from safetyplan.sku.recommend import build_basket, recommend


def sup(*skus, id="s"):
    return Supplier(id=id, name=id.upper(), skus=list(skus))


def sku(code, provides, price, specs=("IS 2925",), **kw):
    return SKU(sku_code=code, name=code, provides=provides, price=price, specs=list(specs), **kw)


def packs(basket):
    return {l.sku_code: l.packs for l in basket.lines}


class TestPacks:
    def test_27_helmets_cheapest_cover(self):
        # 10-pack Rs 2100 (210/u), 25-pack Rs 4800 (192/u).
        s = sup(sku("H10", {"helmet": 10}, 2100), sku("H25", {"helmet": 25}, 4800))
        b = build_basket({"helmet": 27}, s)
        # Options: 3x10 = 6300, 25+10 = 6900, 2x25 = 9600 -> 3x10.
        assert packs(b) == {"H10": 3} and b.total == 6300
        assert b.coverage[0].supplied == 30 and b.coverage[0].excess == 3

    def test_exact_fit_prefers_big_pack(self):
        s = sup(sku("H10", {"helmet": 10}, 2100), sku("H25", {"helmet": 25}, 4800))
        assert packs(build_basket({"helmet": 50}, s)) == {"H25": 2}

    def test_tie_on_cost_prefers_less_excess(self):
        s = sup(sku("H6", {"helmet": 6}, 600), sku("H5", {"helmet": 5}, 600))
        b = build_basket({"helmet": 5}, s)
        assert packs(b) == {"H5": 1}

    def test_fractional_pack_sizes(self):
        s = sup(sku("R25", {"guardrail_top_rail_m": 2.5}, 300, specs=()))
        b = build_basket({"guardrail_top_rail_m": 11}, s)
        assert packs(b) == {"R25": 5} and b.coverage[0].supplied == 12.5


class TestKits:
    def test_kit_plus_loose_no_shortfall(self):
        s = sup(
            sku("KIT", {"helmet": 25, "reflective_vest": 25}, 5000),
            sku("H1", {"helmet": 1}, 250),
            sku("V1", {"reflective_vest": 1}, 150, specs=()),
        )
        b = build_basket({"helmet": 30, "reflective_vest": 26}, s)
        # kit 5000 + 5 helmets 1250 + 1 vest 150 = 6400 vs loose 7500 + 3900 = 11400
        assert packs(b) == {"KIT": 1, "H1": 5, "V1": 1} and b.total == 6400
        assert all(c.supplied >= c.need for c in b.coverage)

    def test_expensive_kit_not_chosen(self):
        s = sup(sku("KIT", {"helmet": 10, "reflective_vest": 10}, 9000), sku("H1", {"helmet": 1}, 200),
                sku("V1", {"reflective_vest": 1}, 100, specs=()))
        assert "KIT" not in packs(build_basket({"helmet": 10, "reflective_vest": 10}, s))

    def test_unneeded_kit_components_count_as_excess(self):
        # Kit is cheaper per helmet but ships gloves nobody asked for: still chosen on cost,
        # and the gloves are reported nowhere as a shortfall.
        s = sup(sku("KIT", {"helmet": 10, "gloves_pair": 10}, 1500), sku("H10", {"helmet": 10}, 2000))
        b = build_basket({"helmet": 10}, s)
        assert packs(b) == {"KIT": 1}

    def test_local_search_path_for_many_kits(self, monkeypatch):
        monkeypatch.setattr(rec_mod, "MAX_KIT_COMBOS", 1)
        s = sup(sku("KIT", {"helmet": 25, "reflective_vest": 25}, 5000), sku("H1", {"helmet": 1}, 250),
                sku("V1", {"reflective_vest": 1}, 150, specs=()))
        b = build_basket({"helmet": 30, "reflective_vest": 26}, s)
        assert packs(b) == {"KIT": 1, "H1": 5, "V1": 1}


class TestCompliance:
    def test_noncompliant_never_picked_even_if_cheaper(self):
        s = sup(sku("CHEAP", {"full_body_harness": 1}, 500, specs=()),
                sku("CERT", {"full_body_harness": 1}, 1600, specs=("IS 3521",)))
        b = build_basket({"full_body_harness": 4}, s)
        assert packs(b) == {"CERT": 4} and b.excluded_noncompliant == ["CHEAP"]

    def test_kit_with_noncompliant_component_excluded(self):
        s = sup(sku("KIT", {"helmet": 10, "full_body_harness": 2}, 100, specs=("IS 2925",)),
                sku("H10", {"helmet": 10}, 2000))
        assert packs(build_basket({"helmet": 10}, s)) == {"H10": 1}

    def test_only_noncompliant_listed_is_a_gap_with_reason(self):
        s = sup(sku("CHEAP", {"full_body_harness": 1}, 500, specs=()))
        b = build_basket({"full_body_harness": 4}, s)
        assert b.gaps[0].item == "full_body_harness" and "non-compliant" in b.gaps[0].reason


class TestSuppliers:
    def test_gap_reported_and_cheapest_alternative_found(self):
        a = sup(sku("H10", {"helmet": 10}, 2000), id="a")
        b = sup(sku("H10", {"helmet": 10}, 2500), sku("N50", {"safety_net_m2": 50}, 6000, specs=("IS 11057",)), id="b")
        c = sup(sku("N50", {"safety_net_m2": 50}, 5000, specs=("IS 11057",)), id="c")
        r = recommend({"helmet": 10, "safety_net_m2": 40}, [a, b, c])
        # b covers everything -> best even though a is cheaper for helmets.
        assert r.best == "b" and not r.buy_elsewhere

        r = recommend({"helmet": 10, "safety_net_m2": 40}, [a, c])
        assert r.best in ("a", "c")
        (gap,) = r.buy_elsewhere
        assert gap["alternative"] is not None and gap["alternative"]["supplier_id"] != r.best

    def test_budget_flagged_not_enforced(self):
        s = sup(sku("H10", {"helmet": 10}, 2000))
        r = recommend({"helmet": 30}, [s], budget=5000)
        assert r.baskets[0].total == 6000 and r.over_budget_by == 1000

    def test_out_of_stock_used_only_when_nothing_else(self):
        s = sup(sku("OOS", {"helmet": 10}, 1000, in_stock=False), sku("H10", {"helmet": 10}, 2000))
        b = build_basket({"helmet": 10}, s)
        assert packs(b) == {"H10": 1} and not b.warnings
        s2 = sup(sku("OOS", {"helmet": 10}, 1000, in_stock=False))
        b2 = build_basket({"helmet": 10}, s2)
        assert packs(b2) == {"OOS": 1} and "out of stock" in b2.warnings[0]

    def test_brand_preference(self):
        s = sup(sku("X", {"helmet": 10}, 1000, brand="Xbrand"), sku("Y", {"helmet": 10}, 1500, brand="Ybrand"),
                sku("V", {"reflective_vest": 10}, 500, specs=(), brand="Xbrand"))
        b = build_basket({"helmet": 10, "reflective_vest": 10}, s, brand_pref=["ybrand"])
        # Preferred brand used where it exists; other items still bought from whoever has them.
        assert packs(b) == {"Y": 1, "V": 1}


def test_demo_catalogue_basket_covers_tower_needs():
    needs = {"helmet": 44, "guardrail_top_rail_m": 191, "guardrail_mid_rail_m": 191, "toe_board_m": 191,
             "guardrail_post": 106, "full_body_harness": 18}
    r = recommend(needs, list(demo_suppliers()))
    best = r.baskets[0]
    assert r.best == best.supplier_id and not best.gaps
    assert "A-HAR-BUD" not in packs(best)
    assert all(c.supplied >= c.need for c in best.coverage)
    assert best.total == pytest.approx(sum(l.line_total for l in best.lines))
