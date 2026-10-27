"""RawPlan -> PlanGeometry.

Turns loose segments into closed regions, finds the slab outline, splits it into
straight edges and produces hazard *candidates* with exact measurements.
Classification of candidates happens later (heuristics + Muse Spark).
"""

from __future__ import annotations

import math

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from safetyplan.models import Candidate, Edge, PlanGeometry, RawPlan

SNAP_M = 0.005  # endpoint snapping grid
MIN_AREA_M2 = 0.04  # ignore regions smaller than 20x20 cm
SIMPLIFY_M = 0.01
# Morphological opening radius: parts of the slab shallower than R are treated
# as protrusions (balconies, ledges, chajjas are typically 1-2 m deep).
PROTRUSION_R = 2.0
# Polygonized faces bigger than this are rooms, not openings. Explicit closed
# shapes and blocks are not capped (an atrium can be drawn as one polyline).
MAX_FACE_AREA_M2 = 50.0
DEDUPE_IOU = 0.9
ON_OUTLINE_MIN_M = 0.1


def build_geometry(plan: RawPlan) -> PlanGeometry:
    warnings = list(plan.warnings)

    lines = [
        LineString([_snap(s.x1, s.y1), _snap(s.x2, s.y2)])
        for s in plan.segments
        if _snap(s.x1, s.y1) != _snap(s.x2, s.y2)
    ]
    faces = [orient(p) for p in polygonize(unary_union(MultiLineString(lines)))] if lines else []
    faces = [f for f in faces if f.area >= MIN_AREA_M2]
    shapes = []
    for cs in plan.closed_shapes:
        p = Polygon([_snap(x, y) for x, y in cs.points])
        if not p.is_valid:
            p = p.buffer(0)
        if p.geom_type == "Polygon" and p.area >= MIN_AREA_M2:
            shapes.append((orient(p), cs.layer))

    regions = faces + [p for p, _ in shapes]
    if not regions:
        warnings.append("Could not form any closed region; check for gaps in the slab outline.")
        return PlanGeometry([], 0.0, 0.0, [], [], warnings)

    footprint = unary_union(regions)
    main = max(_polys(footprint), key=lambda p: p.area)
    outline = orient(Polygon(main.exterior).simplify(SIMPLIFY_M))
    if len(_polys(footprint)) > 1:
        warnings.append("Plan has several disconnected regions; using the largest as the slab.")

    body = _opening(outline, PROTRUSION_R)

    # Line index used to recover which layers bound each face.
    seg_tree = STRtree(lines) if lines else None
    seg_layers = [s.layer for s in plan.segments if _snap(s.x1, s.y1) != _snap(s.x2, s.y2)]

    raw: list[tuple[str, Polygon, list[str]]] = []
    for p, layer in shapes:
        raw.append(("closed_shape", p, [layer]))
    for f in faces:
        raw.append(("face", f, _boundary_layers(f, seg_tree, seg_layers)))
    for b in plan.blocks:
        if b.bbox:
            bx = Polygon.from_bounds(*b.bbox)
            if bx.area >= MIN_AREA_M2:
                raw.append(("block", bx, [b.layer]))

    kept = _select_candidates(raw, outline)
    candidates = [
        _make_candidate(f"C{i}", src, poly, layers, outline, body)
        for i, (src, poly, layers) in enumerate(
            sorted(kept, key=lambda r: (round(r[1].bounds[1], 2), round(r[1].bounds[0], 2))), 1
        )
    ]
    _attach_labels(candidates, plan)

    coords = list(outline.exterior.coords)
    edges = [
        Edge(f"E{i}", _r(a), _r(b), round(math.dist(a, b), 3))
        for i, (a, b) in enumerate(zip(coords, coords[1:]), 1)
    ]

    return PlanGeometry(
        outline=[_r(c) for c in coords[:-1]],
        outline_area=round(outline.area, 3),
        outline_perimeter=round(outline.length, 3),
        edges=edges,
        candidates=candidates,
        warnings=warnings,
    )


def _select_candidates(raw, outline: Polygon):
    """Drop regions that are the slab itself, duplicates, or nested detail.

    Priority: explicit closed shapes > block boxes > polygonized faces, so a
    stair drawn as a closed polyline with tread lines inside becomes one
    candidate instead of a dozen tread faces.
    """
    rank = {"closed_shape": 0, "block": 1, "face": 2}
    raw = sorted(raw, key=lambda r: (rank[r[0]], -r[1].area))
    kept: list[tuple[str, Polygon, list[str]]] = []
    for src, poly, layers in raw:
        if poly.area > 0.5 * outline.area:
            continue  # the slab / building body itself
        if src == "face" and poly.area > MAX_FACE_AREA_M2:
            continue
        dup = False
        for i, (ksrc, kpoly, klayers) in enumerate(kept):
            inter = poly.intersection(kpoly).area
            if inter / poly.union(kpoly).area >= DEDUPE_IOU:
                kept[i] = (ksrc, kpoly, sorted(set(klayers) | set(layers)))
                dup = True
                break
            # Detail drawn inside a higher-priority region (treads, shaft X-cross).
            if rank[src] > rank[ksrc] and inter >= 0.95 * poly.area:
                dup = True
                break
        if not dup:
            kept.append((src, poly, layers))
    return kept


def _make_candidate(cid, src, poly: Polygon, layers, outline: Polygon, body) -> Candidate:
    mrr = poly.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    sides = sorted([math.dist(c[0], c[1]), math.dist(c[1], c[2])])
    shared = poly.boundary.intersection(outline.exterior.buffer(SNAP_M)).length
    outside = poly.difference(body).area if body is not None else 0.0
    return Candidate(
        id=cid,
        source=src,
        polygon=[_r(p) for p in list(poly.exterior.coords)[:-1]],
        area=round(poly.area, 3),
        perimeter=round(poly.length, 3),
        bbox=tuple(round(v, 3) for v in poly.bounds),
        min_dim=round(sides[0], 3),
        max_dim=round(sides[1], 3),
        layers=sorted(set(layers)),
        on_outline=shared >= ON_OUTLINE_MIN_M,
        outline_shared_len=round(shared, 3),
        protrudes=poly.area > 0 and outside / poly.area > 0.5,
    )


def _attach_labels(cands: list[Candidate], plan: RawPlan) -> None:
    """Give each text/block to the smallest candidate that contains it."""
    polys = [Polygon(c.polygon) for c in cands]

    def smallest_containing(x, y):
        pt = Point(x, y)
        best = None
        for i, p in enumerate(polys):
            if p.covers(pt) and (best is None or p.area < polys[best].area):
                best = i
        return best

    for t in plan.texts:
        i = smallest_containing(t.x, t.y)
        if i is not None:
            cands[i].texts.append(t.text)
    for b in plan.blocks:
        cx, cy = (
            ((b.bbox[0] + b.bbox[2]) / 2, (b.bbox[1] + b.bbox[3]) / 2) if b.bbox else (b.x, b.y)
        )
        i = smallest_containing(cx, cy)
        if i is not None and b.name not in cands[i].blocks:
            cands[i].blocks.append(b.name)


def _boundary_layers(face: Polygon, tree, seg_layers) -> list[str]:
    if tree is None:
        return []
    ring = face.exterior.buffer(SNAP_M * 2)
    hits = tree.query(ring, predicate="contains")
    return sorted({seg_layers[i] for i in hits})


def _opening(poly: Polygon, r: float):
    opened = poly.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")
    return opened if not opened.is_empty else None


def _polys(geom) -> list[Polygon]:
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]


def _snap(x: float, y: float) -> tuple[float, float]:
    return (round(round(x / SNAP_M) * SNAP_M, 4), round(round(y / SNAP_M) * SNAP_M, 4))


def _r(p) -> tuple[float, float]:
    return (round(p[0], 3), round(p[1], 3))
