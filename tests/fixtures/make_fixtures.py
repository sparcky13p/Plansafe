"""Synthetic floor plans with known dimensions, generated with ezdxf.

Run directly to write the DXFs into tests/fixtures/out/ for manual inspection:
    python -m tests.fixtures.make_fixtures
"""

from __future__ import annotations

from pathlib import Path

import ezdxf


def _rect(msp, x0, y0, x1, y1, layer):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


def _rect_lines(msp, x0, y0, x1, y1, layer="0"):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b, dxfattribs={"layer": layer})


def tower_mm(path: Path) -> Path:
    """Layered plan in millimetres.

    Slab 20 x 15 m, balcony 4 x 1.2 m off the south edge, lift shaft 2.5 x 2.5 m
    (with X-cross), stair void 2.7 x 5.0 m (with treads), duct 0.6 x 0.6 m,
    a 1 x 1 m cut-out drawn as a block, an interior wall and a dimension line.

    Expected: outline perimeter 72.4 m, area 304.8 m2.
    """
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    _rect(msp, 0, 0, 20000, 15000, "SLAB")
    _rect(msp, 8000, -1200, 12000, 0, "BALCONY")

    _rect(msp, 3000, 10000, 5500, 12500, "LIFT")
    msp.add_line((3000, 10000), (5500, 12500), dxfattribs={"layer": "LIFT"})
    msp.add_line((3000, 12500), (5500, 10000), dxfattribs={"layer": "LIFT"})

    _rect(msp, 6000, 9500, 8700, 14500, "STAIR")
    for y in range(9750, 14500, 250):
        msp.add_line((6000, y), (8700, y), dxfattribs={"layer": "STAIR"})

    _rect(msp, 15000, 7000, 15600, 7600, "DUCT")

    blk = doc.blocks.new("OPENING_CUTOUT")
    blk.add_lwpolyline([(0, 0), (1000, 0), (1000, 1000), (0, 1000)], close=True)
    msp.add_blockref("OPENING_CUTOUT", (16000, 12000), dxfattribs={"layer": "OPENINGS"})

    msp.add_line((13000, 0), (13000, 15000), dxfattribs={"layer": "WALL"})
    msp.add_line((0, -3000), (20000, -3000), dxfattribs={"layer": "DIMENSIONS"})

    msp.add_text("LIFT", dxfattribs={"layer": "ANNO-TEXT", "insert": (4000, 11000)})
    msp.add_text("STAIRCASE", dxfattribs={"layer": "ANNO-TEXT", "insert": (7000, 12000)})
    msp.add_text("DUCT", dxfattribs={"layer": "ANNO-TEXT", "insert": (15100, 7200)})
    msp.add_text("BALCONY", dxfattribs={"layer": "ANNO-TEXT", "insert": (9000, -600)})

    doc.saveas(path)
    return path


def flat_m(path: Path) -> Path:
    """Unlayered, unitless plan in metres drawn with loose LINEs.

    Slab 12 x 10 m with a 2 mm gap at one corner, a 1.5 x 1.5 m cut-out and a
    2.7 x 3.5 m stair, labelled only by text. Expected perimeter 44 m.
    """
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0
    msp = doc.modelspace()

    msp.add_line((0, 0), (12, 0))
    msp.add_line((12, 0), (12, 10))
    msp.add_line((12, 10), (0, 10))
    msp.add_line((0, 10), (0.002, 0.0))  # imperfect closure

    _rect_lines(msp, 5, 5, 6.5, 6.5)
    msp.add_text("CUT OUT", dxfattribs={"insert": (5.2, 5.7)})

    _rect_lines(msp, 1, 6, 3.7, 9.5)
    msp.add_text("STAIR UP", dxfattribs={"insert": (1.5, 7.5)})

    doc.saveas(path)
    return path


ALL = {"tower_mm.dxf": tower_mm, "flat_m.dxf": flat_m}


def build_all(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return {name: fn(out_dir / name) for name, fn in ALL.items()}


if __name__ == "__main__":
    for name, p in build_all(Path(__file__).parent / "out").items():
        print(p)
