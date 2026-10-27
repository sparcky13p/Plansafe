"""Core data structures shared by ingest, geometry, detection and rules.

All coordinates and lengths are in metres once they leave the ingest layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Point = tuple[float, float]


@dataclass
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "0"


@dataclass
class TextLabel:
    text: str
    x: float
    y: float
    layer: str = "0"


@dataclass
class BlockRef:
    name: str
    x: float
    y: float
    layer: str = "0"
    bbox: tuple[float, float, float, float] | None = None  # minx, miny, maxx, maxy


@dataclass
class ClosedShape:
    points: list[Point]
    layer: str = "0"
    handle: str | None = None


@dataclass
class RawPlan:
    """Plan geometry after ingest, already scaled to metres."""

    source: Literal["dxf", "pdf"]
    unit_scale: float  # drawing units -> metres factor that was applied
    segments: list[Segment] = field(default_factory=list)
    closed_shapes: list[ClosedShape] = field(default_factory=list)
    texts: list[TextLabel] = field(default_factory=list)
    blocks: list[BlockRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


CandidateSource = Literal["closed_shape", "face", "block"]


@dataclass
class Candidate:
    """A closed region that might be a hazard (opening, shaft, stair, balcony)."""

    id: str
    source: CandidateSource
    polygon: list[Point]
    area: float
    perimeter: float
    bbox: tuple[float, float, float, float]
    min_dim: float  # short side of minimum rotated rectangle
    max_dim: float
    layers: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    on_outline: bool = False  # shares boundary with slab outline (balcony-like)
    outline_shared_len: float = 0.0
    protrudes: bool = False  # lies (mostly) outside the main slab body

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Edge:
    """One straight piece of the slab outline (an exposed edge candidate)."""

    id: str
    p1: Point
    p2: Point
    length: float
    facing: str = ""  # north/east/south/west by outward normal, plan north = +y

    def to_dict(self) -> dict:
        return asdict(self)


HazardType = Literal["stair", "lift_shaft", "duct_shaft", "floor_opening", "balcony", "other"]
HAZARD_TYPES: tuple[str, ...] = HazardType.__args__  # type: ignore[attr-defined]


@dataclass
class Detection:
    """Final label for one candidate after merging heuristics and Muse Spark."""

    candidate_id: str
    type: HazardType
    confidence: float
    source: Literal["heuristic", "muse", "both", "none"]
    needs_review: bool
    heuristic_type: HazardType | None = None
    muse_type: HazardType | None = None
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlanGeometry:
    outline: list[Point]
    outline_area: float
    outline_perimeter: float
    edges: list[Edge]
    candidates: list[Candidate]
    warnings: list[str] = field(default_factory=list)

    def candidate(self, cid: str) -> Candidate:
        return next(c for c in self.candidates if c.id == cid)

    @classmethod
    def from_dict(cls, d: dict) -> "PlanGeometry":
        return cls(
            outline=[tuple(p) for p in d["outline"]],
            outline_area=d["outline_area"],
            outline_perimeter=d["outline_perimeter"],
            edges=[Edge(**{**e, "p1": tuple(e["p1"]), "p2": tuple(e["p2"])}) for e in d["edges"]],
            candidates=[Candidate(**{**c, "polygon": [tuple(p) for p in c["polygon"]],
                                     "bbox": tuple(c["bbox"])}) for c in d["candidates"]],
            warnings=list(d.get("warnings", [])),
        )

    def to_dict(self) -> dict:
        return {
            "outline": self.outline,
            "outline_area": self.outline_area,
            "outline_perimeter": self.outline_perimeter,
            "edges": [e.to_dict() for e in self.edges],
            "candidates": [c.to_dict() for c in self.candidates],
            "warnings": self.warnings,
        }
