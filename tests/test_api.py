from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"ok": True}


def test_geometry_upload(fixtures):
    data = fixtures["tower_mm.dxf"].read_bytes()
    r = client.post("/api/geometry", files={"file": ("tower.dxf", data, "application/dxf")})
    assert r.status_code == 200
    body = r.json()
    assert round(body["outline_perimeter"], 1) == 72.4
    assert len(body["candidates"]) >= 5


def test_rejects_non_dxf():
    r = client.post("/api/geometry", files={"file": ("plan.png", b"x", "image/png")})
    assert r.status_code == 415


def test_garbage_dxf_is_422():
    r = client.post("/api/geometry", files={"file": ("bad.dxf", b"not a dxf", "application/dxf")})
    assert r.status_code == 422
