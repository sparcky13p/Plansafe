import json

import httpx
import pytest

from safetyplan.detect.heuristics import label_candidate
from safetyplan.detect.muse import (
    MockMuse,
    MuseError,
    OpenAICompatibleMuse,
    classify,
    client_from_env,
)
from safetyplan.detect.pipeline import detect
from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf
from safetyplan.ingest.render import render_png
from safetyplan.models import Candidate

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def cand(cid="C1", texts=(), blocks=(), layers=(), size=(1.0, 1.0), on_outline=False, protrudes=False):
    w, h = size
    return Candidate(
        id=cid, source="closed_shape", polygon=[(0, 0), (w, 0), (w, h), (0, h)], area=w * h,
        perimeter=2 * (w + h), bbox=(0, 0, w, h), min_dim=min(size), max_dim=max(size),
        layers=list(layers), texts=list(texts), blocks=list(blocks),
        on_outline=on_outline, protrudes=protrudes,
    )


@pytest.fixture(scope="module")
def tower(fixtures):
    raw = load_dxf(fixtures["tower_mm.dxf"])
    return raw, build_geometry(raw)


@pytest.fixture(scope="module")
def flat(fixtures):
    raw = load_dxf(fixtures["flat_m.dxf"])
    return raw, build_geometry(raw)


def by_text(geom, dets, text):
    c = next(c for c in geom.candidates if any(text in t for t in c.texts))
    return next(d for d in dets if d.candidate_id == c.id)


class TestHeuristics:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("LIFT", "lift_shaft"),
            ("LIFT SHAFT", "lift_shaft"),
            ("Elevator", "lift_shaft"),
            ("STAIRCASE", "stair"),
            ("STAIR UP", "stair"),
            ("DUCT", "duct_shaft"),
            ("PLUMBING SHAFT", "duct_shaft"),
            ("CUT OUT", "floor_opening"),
            ("O.T.S.", "floor_opening"),
            ("OPEN TO SKY", "floor_opening"),
            ("SIT-OUT", "balcony"),
            ("BALCONY", "balcony"),
        ],
    )
    def test_text_keywords(self, text, expected):
        lab = label_candidate(cand(texts=[text]))
        assert lab is not None and lab.type == expected

    def test_block_name_with_underscores(self):
        assert label_candidate(cand(blocks=["OPENING_CUTOUT"])).type == "floor_opening"

    def test_unlabelled_protrusion_is_balcony(self):
        lab = label_candidate(cand(size=(1.2, 4.0), on_outline=True, protrudes=True))
        assert lab.type == "balcony"
        assert lab.confidence < 0.7  # geometry alone is a hint, not proof

    def test_room_name_gives_nothing(self):
        assert label_candidate(cand(texts=["BEDROOM"], layers=["WALL"])) is None

    def test_text_plus_layer_is_confident(self):
        lab = label_candidate(cand(texts=["LIFT"], layers=["LIFT"]))
        assert lab.score == 4.0 and lab.confidence >= 0.85


class TestRender:
    def test_png_with_bounded_size(self, tower):
        raw, geom = tower
        png = render_png(raw, geom, max_px=800)
        assert png.startswith(PNG_MAGIC)
        from PIL import Image
        import io

        w, h = Image.open(io.BytesIO(png)).size
        assert max(w, h) <= 800 and min(w, h) > 100


class TestClassify:
    def test_valid_answer(self):
        cs = [cand("C1"), cand("C2")]
        labels, warnings = classify(MockMuse(), b"png", cs)
        assert set(labels) == {"C1", "C2"} and not warnings

    def test_retries_once_after_bad_json(self):
        mock = MockMuse(replies=["Sure! Here are the labels: not json"])
        labels, _ = classify(mock, b"png", [cand("C1")])
        assert mock.calls == 2 and "C1" in labels

    def test_accepts_fenced_json(self):
        reply = '```json\n{"labels":[{"id":"C1","type":"stair","confidence":0.9}]}\n```'
        labels, _ = classify(MockMuse(replies=[reply]), b"png", [cand("C1")])
        assert labels["C1"].type == "stair"

    def test_invalid_type_then_fails(self):
        bad = json.dumps({"labels": [{"id": "C1", "type": "staircase", "confidence": 0.9}]})
        with pytest.raises(MuseError):
            classify(MockMuse(replies=[bad, bad]), b"png", [cand("C1")])

    def test_unknown_and_missing_ids_warn(self):
        reply = json.dumps({"labels": [{"id": "C9", "type": "stair", "confidence": 0.9}]})
        labels, warnings = classify(MockMuse(replies=[reply]), b"png", [cand("C1")])
        assert labels == {}
        assert any("C9" in w for w in warnings) and any("C1" in w for w in warnings)


class TestPipeline:
    def test_tower_all_classified_and_agreeing(self, tower):
        raw, geom = tower
        res = detect(geom, render_png(raw, geom), MockMuse())
        assert res.detector == "mock"
        expected = {"LIFT": "lift_shaft", "STAIRCASE": "stair", "DUCT": "duct_shaft", "BALCONY": "balcony"}
        for text, t in expected.items():
            d = by_text(geom, res.detections, text)
            assert (d.type, d.source, d.needs_review) == (t, "both", False), d
        cut = next(d for d in res.detections
                   if "OPENING_CUTOUT" in geom.candidate(d.candidate_id).blocks)
        assert cut.type == "floor_opening" and cut.source == "both"

    def test_disagreement_prefers_drawing_text_and_flags_review(self, flat):
        raw, geom = flat
        res = detect(geom, render_png(raw, geom), MockMuse())
        cut = by_text(geom, res.detections, "CUT OUT")
        # Mock "vision" sees a 1.5 m square and guesses lift; the drawing says cut-out.
        assert cut.muse_type == "lift_shaft" and cut.heuristic_type == "floor_opening"
        assert cut.type == "floor_opening" and cut.needs_review
        stair = by_text(geom, res.detections, "STAIR")
        assert stair.type == "stair" and not stair.needs_review

    def test_falls_back_to_heuristics_when_model_fails(self, tower):
        raw, geom = tower
        res = detect(geom, b"png", MockMuse(replies=["x", "y"]))
        assert res.detector == "heuristics-only"
        assert any("Vision model unavailable" in w for w in res.warnings)
        assert by_text(geom, res.detections, "LIFT").type == "lift_shaft"

    def test_no_evidence_is_other_and_needs_review(self):
        from safetyplan.detect.pipeline import merge

        d = merge("C1", None, None)
        assert (d.type, d.source, d.needs_review) == ("other", "none", True)


class TestLiveClient:
    def test_openai_compatible_request_shape(self):
        seen = {}

        def handler(req: httpx.Request):
            seen["url"] = str(req.url)
            seen["auth"] = req.headers["authorization"]
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"labels": []}'}}]})

        client = OpenAICompatibleMuse("k", "https://muse.example/v1/", "muse-x", transport=httpx.MockTransport(handler))
        out = client.complete("sys", "hello", b"\x89PNG")
        assert out == '{"labels": []}'
        assert seen["url"] == "https://muse.example/v1/chat/completions"
        assert seen["auth"] == "Bearer k"
        body = seen["body"]
        assert body["model"] == "muse-x" and body["temperature"] == 0
        image = body["messages"][1]["content"][1]["image_url"]["url"]
        assert image.startswith("data:image/png;base64,")

    def test_http_error_raises(self):
        t = httpx.MockTransport(lambda r: httpx.Response(401, text="bad key"))
        with pytest.raises(MuseError, match="401"):
            OpenAICompatibleMuse("k", "https://m", "x", transport=t).complete("s", "u", None)

    def test_env_selection(self, monkeypatch):
        monkeypatch.delenv("MUSE_API_KEY", raising=False)
        assert isinstance(client_from_env(), MockMuse)
        monkeypatch.setenv("MUSE_API_KEY", "k")
        monkeypatch.delenv("MUSE_API_BASE", raising=False)
        with pytest.raises(MuseError):
            client_from_env()
        monkeypatch.setenv("MUSE_API_BASE", "https://m")
        monkeypatch.setenv("MUSE_MODEL", "x")
        assert isinstance(client_from_env(), OpenAICompatibleMuse)
