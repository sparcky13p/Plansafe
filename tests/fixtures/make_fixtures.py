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



def tower_pdf(path: Path) -> Path:
    """A vector PDF at 1:100 on A3: 20 x 15 m slab, 2.5 m lift with X, 1 m cut-out.

    1:100 -> 1 m = 10 mm on paper = 28.3465 pt. Expected perimeter 70 m.
    """
    import pymupdf

    k = 72 / 25.4 * 10  # pt per metre at 1:100
    doc = pymupdf.open()
    page = doc.new_page(width=1191, height=842)
    ox, oy = 100, 700  # origin (PDF y grows downward)

    def P(x, y):
        return pymupdf.Point(ox + x * k, oy - y * k)

    def rect(x0, y0, x1, y1):
        page.draw_rect(pymupdf.Rect(P(x0, y1), P(x1, y0)), color=(0, 0, 0), width=0.5)

    rect(0, 0, 20, 15)
    rect(3, 10, 5.5, 12.5)
    page.draw_line(P(3, 10), P(5.5, 12.5), color=(0, 0, 0), width=0.3)
    page.draw_line(P(3, 12.5), P(5.5, 10), color=(0, 0, 0), width=0.3)
    rect(16, 12, 17, 13)
    page.insert_text(P(3.6, 11.0), "LIFT", fontsize=8)
    page.insert_text(P(16.1, 12.4), "CUT OUT", fontsize=5)
    page.insert_text(pymupdf.Point(900, 800), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=10)
    doc.save(path)
    return path


ALL["tower_pdf.pdf"] = tower_pdf


def lines_only(path: Path) -> Path:
    """Everything drawn with loose LINEs, no labels, metres.

    Slab 16 x 12 m; lift 2.4 x 2.4 m with an X-cross; stair 2.6 x 4.5 m with
    tread lines every 0.3 m. Both must come out as single candidates.
    """
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    _rect_lines(msp, 0, 0, 16, 12)
    _rect_lines(msp, 2, 8, 4.4, 10.4)
    msp.add_line((2, 8), (4.4, 10.4))
    msp.add_line((2, 10.4), (4.4, 8))
    _rect_lines(msp, 8, 6, 10.6, 10.5)
    y = 6.3
    while y < 10.5 - 1e-9:
        msp.add_line((8, y), (10.6, y))
        y += 0.3
    doc.saveas(path)
    return path


ALL["lines_only.dxf"] = lines_only


if __name__ == "__main__":
    for name, p in build_all(Path(__file__).parent / "out").items():
        print(p)
