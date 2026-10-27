"""FastAPI entry point (Vercel Python function).

Local: uvicorn api.index:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile

from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf

app = FastAPI(title="SafetyPlan API", version="0.1.0")

# Vercel caps request bodies at 4.5 MB; larger plans go through Blob (run 5).
MAX_DIRECT_UPLOAD = 4 * 1024 * 1024


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/geometry")
async def geometry(file: UploadFile) -> dict:
    if not (file.filename or "").lower().endswith(".dxf"):
        raise HTTPException(415, "Only DXF is supported for now.")
    data = await file.read()
    if len(data) > MAX_DIRECT_UPLOAD:
        raise HTTPException(413, "File too large for direct upload.")
    try:
        raw = load_dxf(data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read DXF: {exc}") from exc
    return build_geometry(raw).to_dict()
