"""Muse Spark adapter: classify measured candidates on a rendered plan.

The model only *labels* candidate IDs; it never produces dimensions. Any
answer is validated against a strict schema and retried once on failure.

The live client speaks the OpenAI-compatible chat-completions format
(base URL / key / model from env). Swap the class if the hosted API differs.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from safetyplan.models import HAZARD_TYPES, Candidate, HazardType

SYSTEM_PROMPT = f"""You are a construction safety engineer reading an architectural floor plan.
The image shows the plan. Red outlines with red ID labels (C1, C2, ...) mark candidate regions.
For EVERY candidate ID, decide what it is:
- stair: staircase or stair void (tread lines, UP/DN arrows)
- lift_shaft: elevator / lift well (often a square with an X cross)
- duct_shaft: small service shaft or duct (plumbing, electrical, ventilation)
- floor_opening: cut-out, void, open-to-sky (OTS), double-height opening
- balcony: balcony, sit-out, terrace or deck at the slab edge
- other: rooms, columns, furniture, anything that is not a fall hazard
Use the candidate measurements and text hints provided. Do not invent IDs.
Respond with JSON only, exactly in this form:
{{"labels": [{{"id": "C1", "type": "<one of {', '.join(HAZARD_TYPES)}>", "confidence": 0.0-1.0, "reason": "<short>"}}]}}"""


class MuseLabel(BaseModel):
    id: str
    type: HazardType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class MuseResponse(BaseModel):
    labels: list[MuseLabel]


class MuseError(RuntimeError):
    pass


class MuseClient(Protocol):
    name: str

    def complete(self, system: str, user_text: str, image_png: bytes | None) -> str:
        """Return the model's raw text answer."""


def candidate_payload(cands: list[Candidate]) -> list[dict]:
    return [
        {
            "id": c.id,
            "size_m": [c.min_dim, c.max_dim],
            "area_m2": c.area,
            "texts": c.texts,
            "blocks": c.blocks,
            "layers": c.layers,
            "on_slab_edge": c.on_outline,
            "projects_beyond_slab": c.protrudes,
        }
        for c in cands
    ]


def classify(client: MuseClient, image_png: bytes, cands: list[Candidate]) -> tuple[dict[str, MuseLabel], list[str]]:
    """Ask the model to label every candidate. Returns (labels by id, warnings)."""
    if not cands:
        return {}, []
    user = "Candidates:\n" + json.dumps(candidate_payload(cands), indent=1)
    known = {c.id for c in cands}
    warnings: list[str] = []

    last_err = ""
    for attempt in range(2):
        prompt = user if attempt == 0 else (
            f"{user}\n\nYour previous answer was invalid ({last_err}). Reply with valid JSON only."
        )
        raw = client.complete(SYSTEM_PROMPT, prompt, image_png)
        try:
            resp = MuseResponse.model_validate(_extract_json(raw))
        except (ValueError, ValidationError) as exc:
            last_err = str(exc).splitlines()[0][:200]
            continue
        labels: dict[str, MuseLabel] = {}
        for lab in resp.labels:
            if lab.id not in known:
                warnings.append(f"Muse returned unknown candidate id {lab.id}; ignored.")
            else:
                labels[lab.id] = lab
        missing = known - labels.keys()
        if missing:
            warnings.append(f"Muse gave no label for {', '.join(sorted(missing, key=_id_num))}.")
        return labels, warnings
    raise MuseError(f"Muse response invalid after retry: {last_err}")


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def _id_num(cid: str) -> int:
    return int(cid[1:]) if cid[1:].isdigit() else 0


class OpenAICompatibleMuse:
    """Hosted Muse Spark behind an OpenAI-compatible /chat/completions API."""

    name = "muse"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.model = model
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def complete(self, system: str, user_text: str, image_png: bytes | None) -> str:
        content: list[dict] = [{"type": "text", "text": user_text}]
        if image_png:
            b64 = base64.b64encode(image_png).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        r = self._http.post("/chat/completions", json=body)
        if r.status_code >= 400:
            raise MuseError(f"Muse API {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


class MockMuse:
    """Deterministic stand-in that classifies from candidate shape alone.

    It deliberately ignores text hints so tests exercise the merge between an
    independent "vision" opinion and the keyword heuristics.
    """

    name = "mock"

    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies or [])  # canned raw replies, consumed first
        self.calls = 0

    def complete(self, system: str, user_text: str, image_png: bytes | None) -> str:
        self.calls += 1
        if self.replies:
            return self.replies.pop(0)
        from safetyplan.instructions.parse import PARSER_MARKER, mock_reply

        if PARSER_MARKER in system:
            return mock_reply(user_text)
        cands = json.loads(user_text.split("Candidates:\n", 1)[1].split("\n\nYour previous", 1)[0])
        return json.dumps({"labels": [self._guess(c) for c in cands]})

    @staticmethod
    def _guess(c: dict) -> dict:
        short, long = c["size_m"]
        aspect = long / short if short else 99
        if c["projects_beyond_slab"] and c["on_slab_edge"]:
            t, conf = "balcony", 0.8
        elif short < 1.0:
            t, conf = "duct_shaft", 0.6
        elif aspect < 1.25 and 1.5 <= short <= 3.5:
            t, conf = "lift_shaft", 0.65
        elif aspect >= 1.25 and 2.0 <= short <= 3.5:
            t, conf = "stair", 0.6
        elif long <= 6.0:
            t, conf = "floor_opening", 0.55
        else:
            t, conf = "other", 0.5
        return {"id": c["id"], "type": t, "confidence": conf, "reason": f"shape {short}x{long} m"}


def client_from_env() -> MuseClient:
    """Live client when MUSE_API_KEY is set, otherwise the mock."""
    key = os.environ.get("MUSE_API_KEY")
    if not key:
        return MockMuse()
    base, model = os.environ.get("MUSE_API_BASE"), os.environ.get("MUSE_MODEL")
    if not base or not model:
        raise MuseError("MUSE_API_KEY is set but MUSE_API_BASE / MUSE_MODEL are missing.")
    return OpenAICompatibleMuse(api_key=key, base_url=base, model=model)
