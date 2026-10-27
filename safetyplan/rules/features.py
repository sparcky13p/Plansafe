"""Confirmed hazard features: the input the rules engine works on.

Built from geometry + detections (after human review). Slab-outline edges
that belong to a balcony are attributed to that balcony so the trace says
"balcony C1" rather than three anonymous edge segments.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from shapely.geometry import LineString, Polygon

from safetyplan.models import Detection, PlanGeometry

HAZARDS = {"stair", "lift_shaft", "duct_shaft", "floor_opening", "balcony"}
EDGE_SNAP_M = 0.02


@dataclass
class Feature:
    id: str  # candidate id (C3) or edge id (E2)
    type: str  # slab_edge | balcony | stair | lift_shaft | duct_shaft | floor_opening
    length: float = 0.0  # exposed edge length to protect
    perimeter: float = 0.0
    area: float = 0.0
    min_dim: float = 0.0
    max_dim: float = 0.0
    edge_ids: list[str] = field(default_factory=list)
    facing: str = ""  # for edges/balconies: direction of the longest exposed edge

    def vars(self) -> dict[str, float]:
        return {
            "length": self.length, "perimeter": self.perimeter, "area": self.area,
            "min_dim": self.min_dim, "max_dim": self.max_dim,
        }

    def to_dict(self) -> dict:
        return asdict(self)


def build_features(
    geom: PlanGeometry,
    detections: list[Detection],
    type_overrides: dict[str, str] | None = None,
    protected_edges: set[str] | None = None,
    added: list[dict] | None = None,
) -> list[Feature]:
    """Turn reviewed detections + outline edges into rule-engine features.

    type_overrides: reviewer relabels, candidate id -> type ("other" removes it).
    protected_edges: edge ids already protected (permanent wall, parapet).
    added: openings the reviewer drew by hand, [{id, type, polygon}].
    """
    type_overrides = type_overrides or {}
    protected = protected_edges or set()
    types = {d.candidate_id: type_overrides.get(d.candidate_id, d.type) for d in detections}

    feats: list[Feature] = []
    balcony_edges: dict[str, list[str]] = {}
    for c in geom.candidates:
        t = types.get(c.id, "other")
        if t not in HAZARDS:
            continue
        f = Feature(c.id, t, c.perimeter, c.perimeter, c.area, c.min_dim, c.max_dim)
        if t == "balcony":
            zone = Polygon(c.polygon).buffer(EDGE_SNAP_M)
            balcony_edges[c.id] = [e.id for e in geom.edges if zone.covers(LineString([e.p1, e.p2]))]
        feats.append(f)

    by_id = {e.id: e for e in geom.edges}
    claimed = {eid for ids in balcony_edges.values() for eid in ids}
    for f in feats:
        if f.type == "balcony":
            # Only the open sides on the slab outline need protection.
            f.edge_ids = [e for e in balcony_edges[f.id] if e not in protected]
            f.length = round(sum(by_id[e].length for e in f.edge_ids), 3)
            if f.edge_ids:
                f.facing = max((by_id[e] for e in f.edge_ids), key=lambda e: e.length).facing

    for e in geom.edges:
        if e.id not in claimed and e.id not in protected:
            feats.append(Feature(e.id, "slab_edge", length=e.length, max_dim=e.length,
                                 edge_ids=[e.id], facing=e.facing))

    for a in added or []:
        feats.append(feature_from_polygon(a["id"], a["type"], a["polygon"]))
    return feats


def feature_from_polygon(fid: str, ftype: str, polygon) -> Feature:
    if ftype not in HAZARDS - {"balcony"}:
        raise ValueError(f"drawn feature {fid}: type must be an opening, stair or shaft, not {ftype!r}")
    p = Polygon(polygon)
    if not p.is_valid or p.area <= 0:
        raise ValueError(f"drawn feature {fid}: polygon is not a valid area")
    c = list(p.minimum_rotated_rectangle.exterior.coords)
    a, b = sorted([math.dist(c[0], c[1]), math.dist(c[1], c[2])])
    return Feature(fid, ftype, round(p.length, 3), round(p.length, 3), round(p.area, 3), round(a, 3), round(b, 3))
