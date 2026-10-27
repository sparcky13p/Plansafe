"""Render a plan to PNG with candidate IDs overlaid (input image for Muse Spark).

The overlay lets the vision model refer to regions by ID, so its answer maps
straight back onto measured geometry.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon

from safetyplan.models import PlanGeometry, RawPlan

MAX_PX = 1600
MARGIN_PX = 40
LINE = (60, 60, 60)
OUTLINE = (20, 40, 160)
CANDIDATE = (220, 30, 30)
TEXT = (110, 110, 110)


@dataclass
class Transform:
    """World (metres, y up) -> image pixels (y down)."""

    minx: float
    maxy: float
    k: float  # px per metre
    margin: int

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.minx) * self.k + self.margin, (self.maxy - y) * self.k + self.margin)


def fit_transform(raw: RawPlan, geom: PlanGeometry, max_px: int = MAX_PX) -> tuple[Transform, int, int]:
    xs = [p[0] for p in geom.outline] + [v for s in raw.segments for v in (s.x1, s.x2)]
    ys = [p[1] for p in geom.outline] + [v for s in raw.segments for v in (s.y1, s.y2)]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1e-6)
    k = (max_px - 2 * MARGIN_PX) / span
    w = int((maxx - minx) * k) + 2 * MARGIN_PX
    h = int((maxy - miny) * k) + 2 * MARGIN_PX
    return Transform(minx, maxy, k, MARGIN_PX), w, h


def render_png(raw: RawPlan, geom: PlanGeometry, max_px: int = MAX_PX) -> bytes:
    """Plan with candidate outlines and ID labels: the vision model's input."""
    img, d, t = _base(raw, geom, max_px, outline_width=3)
    font = _font(max(12, int(max_px / 70)))
    for c in geom.candidates:
        d.line([t(*p) for p in c.polygon + c.polygon[:1]], fill=CANDIDATE, width=3)
    # Labels after all outlines so they are never painted over.
    for c in geom.candidates:
        rp = Polygon(c.polygon).representative_point()
        x, y = t(rp.x, rp.y)
        box = d.textbbox((x, y), c.id, font=font, anchor="mm")
        d.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill="white", outline=CANDIDATE)
        d.text((x, y), c.id, fill=CANDIDATE, font=font, anchor="mm")

    return _png(img)


def render_background(raw: RawPlan, geom: PlanGeometry, max_px: int = 2000) -> tuple[bytes, dict]:
    """Plain drawing for the review screen, plus the transform the SVG overlay uses.

    Overlay maps world (x, y) to pixels with: px = (x - minx) * k + margin,
    py = (maxy - y) * k + margin, on an image of width x height pixels.
    """
    img, _, t = _base(raw, geom, max_px, outline_width=2, line=(150, 150, 150), text=(150, 150, 150))
    view = {"minx": t.minx, "maxy": t.maxy, "k": t.k, "margin": t.margin, "width": img.width, "height": img.height}
    return _png(img), view


def _base(raw, geom, max_px, outline_width, line=LINE, text=TEXT):
    if not geom.outline:
        raise ValueError("Nothing to render: plan has no outline.")
    t, w, h = fit_transform(raw, geom, max_px)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for s in raw.segments:
        d.line([t(s.x1, s.y1), t(s.x2, s.y2)], fill=line, width=1)
    d.line([t(*p) for p in geom.outline + geom.outline[:1]], fill=OUTLINE, width=outline_width)
    # Drawing text (room names, LIFT, OTS...) is context the vision model needs.
    small = _font(max(10, int(max_px / 110)))
    for tl in raw.texts:
        d.text(t(tl.x, tl.y), tl.text, fill=text, font=small, anchor="ls")
    return img, d, t


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


TYPE_COLOURS = {
    "stair": (130, 60, 200), "lift_shaft": (200, 30, 30), "duct_shaft": (230, 120, 0),
    "floor_opening": (220, 160, 0), "balcony": (0, 130, 200),
}


def render_report_png(raw: RawPlan, geom: PlanGeometry, features: list[dict], max_px: int = 1800) -> bytes:
    """Plan for the report: exposed edges red, protected edges green, hazards numbered by id."""
    img, d, t = _base(raw, geom, max_px, outline_width=2, line=(185, 185, 185), text=(170, 170, 170))
    exposed = {eid for f in features for eid in f.get("edge_ids", [])}
    for e in geom.edges:
        colour = (210, 30, 30) if e.id in exposed else (40, 150, 60)
        d.line([t(*e.p1), t(*e.p2)], fill=colour, width=6)
    polys = {c.id: c.polygon for c in geom.candidates}
    font = _font(max(12, int(max_px / 75)))
    for f in features:
        poly = polys.get(f["id"]) or f.get("polygon")
        if not poly or f["type"] == "slab_edge":
            continue
        colour = TYPE_COLOURS.get(f["type"], CANDIDATE)
        d.line([t(*p) for p in list(poly) + [poly[0]]], fill=colour, width=4)
    labels = [(f["id"], polys.get(f["id"]) or f.get("polygon"), TYPE_COLOURS.get(f["type"], CANDIDATE))
              for f in features if f["type"] != "slab_edge"]
    labels += [(e.id, [e.p1, e.p2], (210, 30, 30) if e.id in exposed else (40, 150, 60)) for e in geom.edges]
    for label, poly, colour in labels:
        if not poly:
            continue
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        x, y = t(cx, cy)
        box = d.textbbox((x, y), label, font=font, anchor="mm")
        d.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill="white", outline=colour)
        d.text((x, y), label, fill=colour, font=font, anchor="mm")
    return _png(img)
