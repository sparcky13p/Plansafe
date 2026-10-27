import pytest

from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf


def by_text(geom, text):
    hits = [c for c in geom.candidates if any(text in t for t in c.texts)]
    assert len(hits) == 1, f"expected one candidate labelled {text!r}, got {hits}"
    return hits[0]


@pytest.fixture(scope="module")
def tower(fixtures):
    return build_geometry(load_dxf(fixtures["tower_mm.dxf"]))


@pytest.fixture(scope="module")
def flat(fixtures):
    return build_geometry(load_dxf(fixtures["flat_m.dxf"]))


class TestIngest:
    def test_mm_units_scaled_to_metres(self, fixtures):
        raw = load_dxf(fixtures["tower_mm.dxf"])
        assert raw.unit_scale == 0.001
        assert not raw.warnings

    def test_dimension_layer_ignored_but_text_kept(self, fixtures):
        raw = load_dxf(fixtures["tower_mm.dxf"])
        assert all(s.layer != "DIMENSIONS" for s in raw.segments)
        assert {"LIFT", "STAIRCASE", "DUCT", "BALCONY"} <= {t.text for t in raw.texts}

    def test_block_exploded_and_recorded(self, fixtures):
        raw = load_dxf(fixtures["tower_mm.dxf"])
        (blk,) = raw.blocks
        assert blk.name == "OPENING_CUTOUT"
        assert blk.bbox == pytest.approx((16.0, 12.0, 17.0, 13.0))
        assert any(cs.layer == "OPENINGS" for cs in raw.closed_shapes)

    def test_unitless_small_extents_assumed_metres(self, fixtures):
        raw = load_dxf(fixtures["flat_m.dxf"])
        assert raw.unit_scale == 1.0
        assert any("assumed metres" in w for w in raw.warnings)


class TestTowerGeometry:
    def test_outline_includes_balcony(self, tower):
        assert tower.outline_perimeter == pytest.approx(72.4, abs=0.01)
        assert tower.outline_area == pytest.approx(304.8, abs=0.01)

    def test_edges_sum_to_perimeter(self, tower):
        assert sum(e.length for e in tower.edges) == pytest.approx(72.4, abs=0.01)
        assert len(tower.edges) == 8  # rectangle + 4 balcony sides, south edge split twice

    def test_lift_shaft(self, tower):
        lift = by_text(tower, "LIFT")
        assert lift.source == "closed_shape"
        assert lift.area == pytest.approx(6.25)
        assert lift.perimeter == pytest.approx(10.0)
        assert (lift.min_dim, lift.max_dim) == pytest.approx((2.5, 2.5))
        assert "LIFT" in lift.layers
        assert not lift.on_outline

    def test_stair_treads_collapse_into_one_candidate(self, tower):
        stair = by_text(tower, "STAIRCASE")
        assert stair.area == pytest.approx(13.5)
        assert (stair.min_dim, stair.max_dim) == pytest.approx((2.7, 5.0))
        tread_faces = [c for c in tower.candidates if c.source == "face" and 6 <= c.bbox[0] < 8.7]
        assert not tread_faces

    def test_duct(self, tower):
        duct = by_text(tower, "DUCT")
        assert duct.area == pytest.approx(0.36)
        assert duct.min_dim == pytest.approx(0.6)

    def test_block_cutout(self, tower):
        cut = next(c for c in tower.candidates if "OPENING_CUTOUT" in c.blocks)
        assert cut.area == pytest.approx(1.0)
        assert "OPENINGS" in cut.layers

    def test_balcony_protrudes_and_touches_outline(self, tower):
        bal = by_text(tower, "BALCONY")
        assert bal.area == pytest.approx(4.8)
        assert bal.protrudes
        assert bal.on_outline
        # 4 m front + 2 x 1.2 m sides are on the outline; the 4 m back edge is not.
        assert bal.outline_shared_len == pytest.approx(6.4, abs=0.05)

    def test_internal_hazards_do_not_protrude(self, tower):
        for text in ("LIFT", "STAIRCASE", "DUCT"):
            assert not by_text(tower, text).protrudes

    def test_no_room_sized_faces(self, tower):
        assert all(c.area <= 50 for c in tower.candidates if c.source == "face")

    def test_candidate_ids_unique(self, tower):
        ids = [c.id for c in tower.candidates]
        assert len(ids) == len(set(ids))


class TestFlatGeometry:
    def test_gap_snapped_and_perimeter_exact(self, flat):
        assert flat.outline_perimeter == pytest.approx(44.0, abs=0.01)
        assert flat.outline_area == pytest.approx(120.0, abs=0.05)

    def test_line_drawn_openings_found_via_faces(self, flat):
        cut = by_text(flat, "CUT OUT")
        assert cut.source == "face"
        assert cut.area == pytest.approx(2.25)
        stair = by_text(flat, "STAIR")
        assert stair.area == pytest.approx(9.45)

    def test_serialises(self, flat):
        d = flat.to_dict()
        assert d["candidates"] and d["edges"]
