"""Site photo check (stretch): is the planned protection visible on site?

SAM 3.1 segments concepts named by text prompts ("guardrail", "floor
opening"...). For each hazard the user says the photo shows, we look for the
hazard and for protection next to it. Results are hints for a person to
verify - "possibly unprotected", never a verdict.

The hosted SAM API contract is assumed (see HttpSam) and isolated here.
"""

from __future__ import annotations

import base64
import os
from dataclasses import asdict, dataclass, field
from typing import Protocol

import httpx

HAZARD_PROMPTS = {
    "slab_edge": ["slab edge", "open floor edge"],
    "balcony": ["balcony edge", "open floor edge"],
    "floor_opening": ["floor opening", "hole in floor"],
    "duct_shaft": ["floor opening", "hole in floor"],
    "lift_shaft": ["lift shaft opening", "elevator shaft"],
    "stair": ["stair opening", "staircase"],
}
PROTECTION_PROMPTS = ["guardrail", "safety railing", "safety net", "hole cover", "barricade"]
HAZARD_MIN = 0.5
PROTECTION_MIN = 0.4


class SamError(RuntimeError):
    pass


@dataclass
class Mask:
    prompt: str
    score: float
    bbox: tuple[float, float, float, float]  # normalised 0..1 (x0, y0, x1, y1)


class SamClient(Protocol):
    name: str

    def segment(self, image: bytes, prompts: list[str]) -> list[Mask]: ...


class HttpSam:
    """Assumed contract: POST {base}/segment
         {"model", "image": <base64>, "prompts": [...]}
       -> {"masks": [{"prompt", "score", "bbox": [x0, y0, x1, y1]}]}  (bbox normalised)
    """

    name = "sam"

    def __init__(self, api_key: str, base_url: str, model: str, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers={"Authorization": f"Bearer {api_key}"},
                                  timeout=120, transport=transport)

    def segment(self, image: bytes, prompts: list[str]) -> list[Mask]:
        r = self._http.post("/segment", json={"model": self.model, "image": base64.b64encode(image).decode(),
                                              "prompts": prompts})
        if r.status_code >= 400:
            raise SamError(f"SAM API {r.status_code}: {r.text[:300]}")
        try:
            return [Mask(m["prompt"], float(m["score"]), tuple(m["bbox"])) for m in r.json()["masks"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SamError(f"Unexpected SAM response: {exc}") from exc


class MockSam:
    name = "mock"

    def __init__(self, masks: list[Mask]):
        self.masks = masks

    def segment(self, image: bytes, prompts: list[str]) -> list[Mask]:
        return [m for m in self.masks if m.prompt in prompts]


def sam_from_env() -> SamClient | None:
    key, base, model = (os.environ.get(k) for k in ("SAM_API_KEY", "SAM_API_BASE", "SAM_MODEL"))
    if not (key and base and model):
        return None
    return HttpSam(key, base, model)


@dataclass
class Finding:
    feature_id: str
    feature_type: str
    status: str  # protection_visible | possibly_unprotected | not_visible
    detail: str
    evidence: list[dict] = field(default_factory=list)


def check_photo(image: bytes, features: list[dict], client: SamClient) -> list[Finding]:
    """features: the plan features this photo shows ({id, type})."""
    prompts = sorted({p for f in features for p in HAZARD_PROMPTS.get(f["type"], [])} | set(PROTECTION_PROMPTS))
    masks = client.segment(image, prompts)
    protection = [m for m in masks if m.prompt in PROTECTION_PROMPTS and m.score >= PROTECTION_MIN]

    findings = []
    for f in features:
        hp = HAZARD_PROMPTS.get(f["type"], [])
        hazards = [m for m in masks if m.prompt in hp and m.score >= HAZARD_MIN]
        if not hazards:
            findings.append(Finding(f["id"], f["type"], "not_visible",
                                    "Could not find this edge/opening in the photo."))
            continue
        h = max(hazards, key=lambda m: m.score)
        near = [p for p in protection if _near(h.bbox, p.bbox)]
        if near:
            best = max(near, key=lambda m: m.score)
            findings.append(Finding(f["id"], f["type"], "protection_visible",
                                    f"{best.prompt} visible next to the {h.prompt} ({best.score:.0%}).",
                                    [asdict(h), asdict(best)]))
        else:
            findings.append(Finding(f["id"], f["type"], "possibly_unprotected",
                                    f"{h.prompt} visible ({h.score:.0%}) but no guardrail, net or cover found "
                                    "next to it. Please check on site.", [asdict(h)]))
    return findings


def _near(a, b, grow: float = 0.15) -> bool:
    ax0, ay0, ax1, ay1 = a
    gx, gy = (ax1 - ax0) * grow, (ay1 - ay0) * grow
    ax0, ay0, ax1, ay1 = ax0 - gx, ay0 - gy, ax1 + gx, ay1 + gy
    bx0, by0, bx1, by1 = b
    return not (bx1 < ax0 or bx0 > ax1 or by1 < ay0 or by0 > ay1)
