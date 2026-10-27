"""DXF -> RawPlan.

Reads model space, explodes block references (keeping their names as hints),
flattens curves to line segments and converts everything to metres.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from ezdxf import bbox as ezbbox
from ezdxf import path as ezpath
from ezdxf import recover
from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic

from safetyplan.models import BlockRef, ClosedShape, RawPlan, Segment, TextLabel

# $INSUNITS code -> metres per drawing unit
INSUNITS_TO_M = {
    1: 0.0254,  # inches
    2: 0.3048,  # feet
    4: 0.001,  # millimetres
    5: 0.01,  # centimetres
    6: 1.0,  # metres
    14: 0.1,  # decimetres
}

# Layers that carry annotation, not building geometry. Matched case-insensitively.
DEFAULT_IGNORE_LAYERS = re.compile(
    r"(DIM|ANNO|HATCH|GRID|AXIS|FURN|TITLE|BORDER|DEFPOINTS|VIEWPORT)", re.I
)

# Flattening tolerance for arcs/splines, in drawing units scaled to ~10 mm.
FLATTEN_M = 0.01

MAX_BLOCK_DEPTH = 6


def load_dxf(
    src: str | Path | bytes,
    unit_scale: float | None = None,
    ignore_layers: re.Pattern | None = DEFAULT_IGNORE_LAYERS,
) -> RawPlan:
    doc = _read(src)
    msp = doc.modelspace()

    warnings: list[str] = []
    scale = unit_scale or _detect_scale(doc, warnings)

    plan = RawPlan(source="dxf", unit_scale=scale, warnings=warnings)
    reader = _Reader(plan, scale, ignore_layers)
    for e in msp:
        reader.visit(e, depth=0)
    if not plan.segments and not plan.closed_shapes:
        warnings.append("No usable geometry found in model space.")
    return plan


def _read(src: str | Path | bytes) -> Drawing:
    # recover.read detects the encoding and tolerates the damaged files that
    # real-world CAD exports often are.
    if isinstance(src, bytes):
        doc, _ = recover.read(io.BytesIO(src))
    else:
        doc, _ = recover.readfile(str(src))
    return doc


def _detect_scale(doc: Drawing, warnings: list[str]) -> float:
    code = doc.header.get("$INSUNITS", 0)
    if code in INSUNITS_TO_M:
        return INSUNITS_TO_M[code]
    # Unitless: guess from extents. Building plans in metres span < 500 units,
    # plans in mm span thousands.
    try:
        ext = ezbbox.extents(doc.modelspace(), fast=True)
        span = max(ext.size.x, ext.size.y) if ext.has_data else 0
    except Exception:
        span = 0
    guess = 0.001 if span > 1000 else 1.0
    warnings.append(
        f"Drawing has no units ($INSUNITS={code}); assumed "
        f"{'millimetres' if guess == 0.001 else 'metres'} from extents ({span:.0f})."
    )
    return guess


class _Reader:
    def __init__(self, plan: RawPlan, scale: float, ignore: re.Pattern | None):
        self.plan = plan
        self.s = scale
        self.ignore = ignore
        self.flatten = FLATTEN_M / scale

    def visit(self, e: DXFGraphic, depth: int) -> None:
        layer = e.dxf.get("layer", "0")
        kind = e.dxftype()
        # Room/shaft names usually sit on annotation layers, so text is always kept.
        if kind not in ("TEXT", "MTEXT") and self.ignore and self.ignore.search(layer):
            return

        if kind == "INSERT":
            self._insert(e, layer, depth)
        elif kind == "LINE":
            s, t = e.dxf.start, e.dxf.end
            self._seg(s.x, s.y, t.x, t.y, layer)
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            self._polyline(e, layer)
        elif kind in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
            self._curve(e, layer, closed=kind == "CIRCLE")
        elif kind in ("TEXT", "MTEXT"):
            self._text(e, layer)
        # HATCH, DIMENSION, POINT, SOLID etc. are ignored on purpose.

    def _insert(self, e, layer: str, depth: int) -> None:
        if depth >= MAX_BLOCK_DEPTH:
            self.plan.warnings.append(f"Block nesting deeper than {MAX_BLOCK_DEPTH}: {e.dxf.name}")
            return
        try:
            children = list(e.virtual_entities())
        except Exception as exc:  # malformed / non-uniform scaled blocks
            self.plan.warnings.append(f"Could not explode block {e.dxf.name}: {exc}")
            return
        box = None
        try:
            ext = ezbbox.extents(children, fast=True)
            if ext.has_data:
                box = (
                    ext.extmin.x * self.s,
                    ext.extmin.y * self.s,
                    ext.extmax.x * self.s,
                    ext.extmax.y * self.s,
                )
        except Exception:
            pass
        ins = e.dxf.insert
        self.plan.blocks.append(BlockRef(e.dxf.name, ins.x * self.s, ins.y * self.s, layer, box))
        for child in children:
            # Entities on layer "0" inside a block inherit the INSERT's layer.
            if child.dxf.get("layer", "0") == "0":
                child.dxf.layer = layer
            self.visit(child, depth + 1)

    def _seg(self, x1, y1, x2, y2, layer: str) -> None:
        s = self.s
        if (x1, y1) == (x2, y2):
            return
        self.plan.segments.append(Segment(x1 * s, y1 * s, x2 * s, y2 * s, layer))

    def _polyline(self, e, layer: str) -> None:
        try:
            p = ezpath.make_path(e)
        except Exception as exc:
            self.plan.warnings.append(f"Skipped polyline {e.dxf.handle}: {exc}")
            return
        pts = [(v.x, v.y) for v in p.flattening(self.flatten)]
        closed = bool(getattr(e, "closed", False) or getattr(e, "is_closed", False))
        if len(pts) >= 2 and pts[0] == pts[-1]:
            closed = True
        self._emit_points(pts, layer, closed, e.dxf.handle)

    def _curve(self, e, layer: str, closed: bool) -> None:
        try:
            p = ezpath.make_path(e)
        except Exception:
            return
        pts = [(v.x, v.y) for v in p.flattening(self.flatten)]
        self._emit_points(pts, layer, closed, e.dxf.handle)

    def _emit_points(self, pts, layer: str, closed: bool, handle) -> None:
        if len(pts) < 2:
            return
        for a, b in zip(pts, pts[1:]):
            self._seg(a[0], a[1], b[0], b[1], layer)
        if closed:
            if pts[0] != pts[-1]:
                self._seg(pts[-1][0], pts[-1][1], pts[0][0], pts[0][1], layer)
            ring = [(x * self.s, y * self.s) for x, y in pts]
            if ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) >= 3:
                self.plan.closed_shapes.append(ClosedShape(ring, layer, handle))

    def _text(self, e, layer: str) -> None:
        if e.dxftype() == "MTEXT":
            text = e.plain_text()
        else:
            text = e.dxf.get("text", "")
        text = " ".join(text.split())
        if not text:
            return
        ins = e.dxf.insert
        self.plan.texts.append(TextLabel(text, ins.x * self.s, ins.y * self.s, layer))
