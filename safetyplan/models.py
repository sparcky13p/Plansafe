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

    def to_dict(self) -> dict:
        return {
            "outline": self.outline,
            "outline_area": self.outline_area,
            "outline_perimeter": self.outline_perimeter,
            "edges": [e.to_dict() for e in self.edges],
            "candidates": [c.to_dict() for c in self.candidates],
            "warnings": self.warnings,
        }
