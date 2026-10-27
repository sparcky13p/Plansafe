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


def test_detect_endpoint_uses_mock_without_key(fixtures, monkeypatch):
    monkeypatch.delenv("MUSE_API_KEY", raising=False)
    data = fixtures["tower_mm.dxf"].read_bytes()
    r = client.post("/api/detect", files={"file": ("tower.dxf", data, "application/dxf")})
    assert r.status_code == 200
    body = r.json()
    assert body["detector"] == "mock"
    types = {d["type"] for d in body["detections"]}
    assert {"lift_shaft", "stair", "duct_shaft", "floor_opening", "balcony"} <= types
    assert len(body["detections"]) == len(body["geometry"]["candidates"])


def test_detect_endpoint_misconfigured_key_falls_back(fixtures, monkeypatch):
    monkeypatch.setenv("MUSE_API_KEY", "k")
    monkeypatch.delenv("MUSE_API_BASE", raising=False)
    data = fixtures["tower_mm.dxf"].read_bytes()
    body = client.post("/api/detect", files={"file": ("t.dxf", data, "application/dxf")}).json()
    assert body["detector"] == "heuristics-only"
    assert any("MUSE_API_BASE" in w for w in body["warnings"])


def test_render_endpoint_returns_png(fixtures):
    data = fixtures["tower_mm.dxf"].read_bytes()
    r = client.post("/api/render", files={"file": ("tower.dxf", data, "application/dxf")})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_rejects_non_dxf():
    r = client.post("/api/geometry", files={"file": ("plan.png", b"x", "image/png")})
    assert r.status_code == 415


def test_garbage_dxf_is_422():
    r = client.post("/api/geometry", files={"file": ("bad.dxf", b"not a dxf", "application/dxf")})
    assert r.status_code == 422


def test_requirements_endpoint(fixtures, monkeypatch):
    import json

    monkeypatch.delenv("MUSE_API_KEY", raising=False)
    data = fixtures["tower_mm.dxf"].read_bytes()
    inputs = json.dumps({"floors": 4, "floor_height": 3.0, "workforce": 40})
    review = json.dumps({"protected_edges": ["E7"]})
    r = client.post(
        "/api/requirements",
        files={"file": ("tower.dxf", data, "application/dxf")},
        data={"inputs": inputs, "review": review},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    q = {x["item"]: x["qty"] for x in body["requirements"]}
    assert q["guardrail_top_rail_m"] == 151 and q["helmet"] == 44
    assert all(f["id"] != "E7" for f in body["features"])


def test_requirements_bad_inputs(fixtures):
    data = fixtures["tower_mm.dxf"].read_bytes()
    r = client.post(
        "/api/requirements",
        files={"file": ("tower.dxf", data, "application/dxf")},
        data={"inputs": '{"floors": 0, "floor_height": 3, "workforce": 1}'},
    )
    assert r.status_code == 422


def test_instruction_parse_endpoint(monkeypatch):
    monkeypatch.delenv("MUSE_API_KEY", raising=False)
    r = client.post("/api/instructions/parse", json={"text": "We already have 25 helmets\nsite near school"})
    body = r.json()
    assert body["instructions"][0]["kind"] == "inventory_on_hand" and body["notes"] == ["site near school"]


def test_supplier_import_endpoint():
    csv = b"code,desc,rate,cat\nZ1,Helmet,2000,Helmet\nZ2,Thing,10,Widget\n"
    r = client.post(
        "/api/suppliers/import",
        files={"file": ("list.csv", csv, "text/csv")},
        data={"supplier_name": "Zed Traders",
              "columns": '{"code": "sku_code", "desc": "name", "rate": "price", "cat": "item"}',
              "item_aliases": '{"Helmet": "helmet"}'},
    )
    body = r.json()
    assert body["supplier"]["id"] == "zed-traders" and len(body["supplier"]["skus"]) == 1
    assert "unknown item 'Widget'" in body["errors"][0]


def test_plan_endpoint_end_to_end(fixtures, monkeypatch):
    import json

    monkeypatch.delenv("MUSE_API_KEY", raising=False)
    data = fixtures["tower_mm.dxf"].read_bytes()
    r = client.post(
        "/api/plan",
        files={"file": ("tower.dxf", data, "application/dxf")},
        data={"inputs": json.dumps({"floors": 4, "floor_height": 3.0, "workforce": 40}),
              "instructions": "We already have 25 helmets\nharness nahi chahiye"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    helmet = next(l for l in body["purchase"]["lines"] if l["item"] == "helmet")
    assert helmet["to_buy"] == 19
    assert body["purchase"]["rejected"][0]["n"] == 2
    rec = body["recommendation"]
    assert rec["best"] == "demo-a" and rec["baskets"][0]["coverage_ratio"] == 1.0
    assert rec["baskets"][0]["total"] > 0


def test_plan_endpoint_with_confirmed_instructions_and_own_price_list(fixtures, monkeypatch):
    import json

    monkeypatch.delenv("MUSE_API_KEY", raising=False)
    confirmed = {"instructions": [{"kind": "inventory_on_hand", "item": "helmet", "qty": 44, "n": 1, "quote": "x"}]}
    csv = b"sku_code,name,item,pack_qty,price,specs\nMY-H,Helmet,helmet,1,1,IS 2925\n"
    r = client.post(
        "/api/plan",
        files={"file": ("tower.dxf", fixtures["tower_mm.dxf"].read_bytes(), "application/dxf"),
               "price_list": ("mine.csv", csv, "text/csv")},
        data={"inputs": json.dumps({"floors": 4, "floor_height": 3.0, "workforce": 40}),
              "confirmed_instructions": json.dumps(confirmed), "supplier_name": "My Shop"},
    )
    body = r.json()
    assert not any(l["item"] == "helmet" and l["to_buy"] for l in body["purchase"]["lines"])
    assert any(b["supplier_id"] == "my-shop" for b in body["recommendation"]["baskets"])
