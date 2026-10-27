"""Combine keyword heuristics and Muse Spark into one label per candidate."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from safetyplan.detect.heuristics import CONFIDENT_SCORE, HeuristicLabel, label_candidate
from safetyplan.detect.muse import MuseClient, MuseError, MuseLabel, classify
from safetyplan.models import Detection, PlanGeometry

# Below this, a label is shown as "please check" in the review step.
REVIEW_BELOW = 0.7


@dataclass
class DetectionResult:
    detections: list[Detection]
    detector: str  # "muse", "mock" or "heuristics-only"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "detector": self.detector,
            "detections": [d.to_dict() for d in self.detections],
            "warnings": self.warnings,
        }


def detect(geom: PlanGeometry, image_png: bytes | None, client: MuseClient | None) -> DetectionResult:
    warnings: list[str] = []
    heur = {c.id: label_candidate(c) for c in geom.candidates}

    muse: dict[str, MuseLabel] = {}
    detector = "heuristics-only"
    if client is not None and image_png is not None and geom.candidates:
        try:
            muse, w = classify(client, image_png, geom.candidates)
            warnings += w
            detector = client.name
        except (MuseError, httpx.HTTPError) as exc:
            warnings.append(f"Vision model unavailable, using drawing labels only: {exc}")

    dets = [merge(c.id, heur[c.id], muse.get(c.id)) for c in geom.candidates]
    return DetectionResult(dets, detector, warnings)


def merge(cid: str, h: HeuristicLabel | None, m: MuseLabel | None) -> Detection:
    ev = list(h.evidence) if h else []
    if m:
        ev.append(f"vision: {m.reason}" if m.reason else "vision model")

    if h and m and h.type == m.type:
        conf = min(0.99, max(h.confidence, m.confidence) + 0.1)
        return Detection(cid, h.type, round(conf, 2), "both", conf < REVIEW_BELOW, h.type, m.type, ev,
                         "drawing labels and vision model agree")
    if h and m:
        # Disagreement. Text written by the drafter beats the vision model when it is strong.
        if h.score >= CONFIDENT_SCORE:
            winner, conf, src = h.type, h.confidence * 0.8, "heuristic"
        else:
            winner, conf, src = m.type, m.confidence * 0.8, "muse"
        return Detection(cid, winner, round(conf, 2), src, True, h.type, m.type, ev,
                         f"drawing suggests {h.type}, vision model suggests {m.type}")
    if h:
        return Detection(cid, h.type, round(h.confidence, 2), "heuristic", h.confidence < REVIEW_BELOW,
                         h.type, None, ev, "from drawing labels")
    if m:
        return Detection(cid, m.type, round(m.confidence, 2), "muse",
                         m.type != "other" and m.confidence < REVIEW_BELOW, None, m.type, ev, "from vision model")
    return Detection(cid, "other", 0.0, "none", True, None, None, ev, "no evidence; please classify")
