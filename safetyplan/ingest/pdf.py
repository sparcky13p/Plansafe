"""Vector PDF -> RawPlan.

PDF drawings have no units, only paper points (1/72 in). The real-world
scale comes from, in order of preference:
  1. a calibration: two points on the sheet (PDF points) and their real distance
  2. an explicit scale ratio (e.g. 100 for 1:100)
  3. a "1:100"-style scale note found in the sheet text
Scanned PDFs (images only) carry no geometry; they are reported, not guessed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import pymupdf

from safetyplan.models import ClosedShape, RawPlan, Segment, TextLabel

PT_TO_M_PAPER = 0.0254 / 72  # one PDF point on paper, in metres
SCALE_RE = re.compile(r"\b1\s*:\s*(\d{2,4})\b")
DEFAULT_RATIO = 100


@dataclass
class Calibration:
    x1: float
    y1: float
    x2: float
    y2: float
    distance_m: float  # real distance between the two points

    def m_per_pt(self) -> float:
        d = math.dist((self.x1, self.y1), (self.x2, self.y2))
        if d <= 0 or self.distance_m <= 0:
            raise ValueError("calibration points must differ and distance must be positive")
        return self.distance_m / d


def pdf_info(data: bytes) -> dict:
    """What the UI needs before calibration: pages, size, detected scale."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pages = []
        for p in doc:
            text = p.get_text()
            m = SCALE_RE.search(text)
            pages.append({
                "width_pt": p.rect.width, "height_pt": p.rect.height,
                "vector_paths": len(p.get_drawings()),
                "images": len(p.get_images()),
                "detected_scale": int(m.group(1)) if m else None,
            })
        return {"pages": pages}


def load_pdf(
    data: bytes,
    page: int = 0,
    calibration: Calibration | None = None,
    scale_ratio: float | None = None,
) -> RawPlan:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if page >= len(doc):
            raise ValueError(f"PDF has {len(doc)} page(s); page {page + 1} requested")
        p = doc[page]
        warnings: list[str] = []
        text = p.get_text()

        if calibration is not None:
            m_per_pt = calibration.m_per_pt()
        elif scale_ratio:
            m_per_pt = PT_TO_M_PAPER * scale_ratio
        else:
            m = SCALE_RE.search(text)
            ratio = int(m.group(1)) if m else DEFAULT_RATIO
            m_per_pt = PT_TO_M_PAPER * ratio
            warnings.append(
                f"Scale {'1:' + str(ratio) + ' read from the drawing' if m else 'not found; assumed 1:100'}"
                " - calibrate with a known dimension to be sure."
            )

        h = p.rect.height
        plan = RawPlan(source="pdf", unit_scale=m_per_pt, warnings=warnings)

        def pt(x, y):
            return (x * m_per_pt, (h - y) * m_per_pt)

        drawings = p.get_drawings()
        for d in drawings:
            if d.get("type") == "f":  # fill-only: hatching / poché, not edges
                continue
            layer = d.get("layer") or "0"
            ring: list[tuple[float, float]] = []
            simple = True
            for it in d["items"]:
                kind = it[0]
                if kind == "l":
                    a, b = pt(*it[1]), pt(*it[2])
                    _seg(plan, a, b, layer)
                    ring.extend([a, b])
                elif kind == "re":
                    r = it[1]
                    corners = [pt(r.x0, r.y0), pt(r.x1, r.y0), pt(r.x1, r.y1), pt(r.x0, r.y1)]
                    for a, b in zip(corners, corners[1:] + corners[:1]):
                        _seg(plan, a, b, layer)
                    plan.closed_shapes.append(ClosedShape(corners, layer))
                    simple = False
                elif kind == "qu":
                    q = it[1]
                    corners = [pt(q.ul.x, q.ul.y), pt(q.ur.x, q.ur.y), pt(q.lr.x, q.lr.y), pt(q.ll.x, q.ll.y)]
                    for a, b in zip(corners, corners[1:] + corners[:1]):
                        _seg(plan, a, b, layer)
                    plan.closed_shapes.append(ClosedShape(corners, layer))
                    simple = False
                elif kind == "c":  # cubic bezier: flatten to 8 pieces
                    p0, c1, c2, p3 = (it[i] for i in range(1, 5))
                    prev = pt(p0.x, p0.y)
                    for k in range(1, 9):
                        tt = k / 8
                        x = ((1 - tt) ** 3) * p0.x + 3 * ((1 - tt) ** 2) * tt * c1.x + 3 * (1 - tt) * tt * tt * c2.x + tt ** 3 * p3.x
                        y = ((1 - tt) ** 3) * p0.y + 3 * ((1 - tt) ** 2) * tt * c1.y + 3 * (1 - tt) * tt * tt * c2.y + tt ** 3 * p3.y
                        cur = pt(x, y)
                        _seg(plan, prev, cur, layer)
                        ring.append(prev)
                        prev = cur
                    ring.append(prev)
                    simple = False
            if simple and d.get("closePath") and len(ring) >= 6:
                pts = _dedupe(ring)
                if len(pts) >= 3:
                    _seg(plan, pts[-1], pts[0], layer)
                    plan.closed_shapes.append(ClosedShape(pts, layer))

        for block in p.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    t = " ".join(span["text"].split())
                    if t:
                        x0, y0, x1, y1 = span["bbox"]
                        plan.texts.append(TextLabel(t, *pt(x0, (y0 + y1) / 2)))

        if not drawings:
            plan.warnings.append(
                "This PDF has no vector drawing (it looks scanned). Upload the DXF or a PDF exported from CAD."
                if p.get_images() else "This PDF page has no drawing."
            )
        return plan


def _seg(plan: RawPlan, a, b, layer):
    if a != b:
        plan.segments.append(Segment(a[0], a[1], b[0], b[1], layer))


def _dedupe(pts):
    out = []
    for q in pts:
        if not out or math.dist(out[-1], q) > 1e-9:
            out.append(q)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out
