"""Keyword + geometry pre-labels for candidates.

These come from what the drafter wrote on the drawing (text, block names,
layer names), so when present they are usually the most reliable signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from safetyplan.models import Candidate, HazardType

# Order matters: "LIFT SHAFT" must hit lift before the generic SHAFT -> duct rule.
PATTERNS: list[tuple[HazardType, re.Pattern]] = [
    ("lift_shaft", re.compile(r"\b(LIFT|ELEV(ATOR)?|L\.?W\.?|LIFT\s*WELL|HOIST)\b", re.I)),
    ("stair", re.compile(r"\b(STAIR(S|CASE|WAY)?|STAIR\s*UP|STEPS?)\b", re.I)),
    ("balcony", re.compile(r"\b(BALC(ONY)?|SIT[\s-]?OUT|VERANDA(H)?|TERRACE|DECK)\b", re.I)),
    (
        "floor_opening",
        re.compile(
            r"(CUT[\s_-]?OUTS?|\bOPENINGS?\b|\bVOID\b|\bO\.?T\.?S\.?\b|OPEN\s*TO\s*SKY|"
            r"DOUBLE\s*HEIGHT|SKY\s*LIGHT|\bSHAFT\s*OPENING\b)",
            re.I,
        ),
    ),
    ("duct_shaft", re.compile(r"\b(DUCTS?|SHAFT|SERVICE|PLUMB(ING)?|ELEC(TRICAL)?\s*SHAFT|P\.?S\.?)\b", re.I)),
]

WEIGHT = {"text": 3.0, "block": 2.0, "layer": 1.0}
PROTRUSION_WEIGHT = 1.5
# Score at which a label counts as confident (one text hit, or block + layer).
CONFIDENT_SCORE = 3.0


@dataclass
class HeuristicLabel:
    type: HazardType
    score: float
    evidence: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        # layer only (1) -> 0.52, protrusion (1.5) -> 0.58, text (3) -> 0.76, text+layer (4) -> 0.88
        return min(0.95, 0.4 + 0.12 * self.score)


def label_candidate(c: Candidate) -> HeuristicLabel | None:
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}

    def hit(t: str, w: float, why: str):
        scores[t] = scores.get(t, 0.0) + w
        evidence.setdefault(t, []).append(why)

    for kind, values in (("text", c.texts), ("block", c.blocks), ("layer", c.layers)):
        for v in dict.fromkeys(values):  # dedupe, keep order
            t = _match(v)
            if t:
                hit(t, WEIGHT[kind], f'{kind} "{v}"')

    if c.protrudes and c.on_outline:
        hit("balcony", PROTRUSION_WEIGHT, "projects beyond the slab outline")

    if not scores:
        return None
    best = max(scores, key=scores.get)
    return HeuristicLabel(best, scores[best], evidence[best])  # type: ignore[arg-type]


def _match(s: str) -> HazardType | None:
    for t, pat in PATTERNS:
        if pat.search(s):
            return t
    return None
