"""Project workflow on top of the pipeline modules.

    upload plan -> analyze (geometry + detection) -> review -> confirm instructions
      -> compute (rules + instructions + SKU basket) -> reports
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from safetyplan.catalog.demo import demo_suppliers
from safetyplan.catalog.importer import FIELDS, _read_rows
from safetyplan.catalog.model import Supplier
from safetyplan.db.models import AuditEvent, Project, SupplierRow
from safetyplan.detect.muse import MuseError, client_from_env
from safetyplan.detect.pipeline import DetectionResult, detect
from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf
from safetyplan.ingest.pdf import PT_TO_M_PAPER, Calibration, load_pdf
from safetyplan.ingest.render import render_background, render_png
from safetyplan.instructions.parse import _item as guess_item
from safetyplan.instructions.schema import GUARDRAIL_SYSTEM, ParsedInstructions
from safetyplan.models import Detection, PlanGeometry, RawPlan
from safetyplan.plan import plan_project
from safetyplan.rules.engine import ProjectInputs
from safetyplan.rules.features import build_features
from safetyplan.server import storage


def muse_client():
    return muse_client_and_warning()[0]


def muse_client_and_warning():
    """(client or None, config warnings)."""
    try:
        return client_from_env(), []
    except MuseError as exc:
        return None, [str(exc)]


def run_detection(raw: RawPlan, geom: PlanGeometry) -> DetectionResult:
    client, warnings = muse_client_and_warning()
    result = detect(geom, render_png(raw, geom), client)
    result.warnings = warnings + result.warnings
    return result


def get_project(db: Session, user: str, pid: str) -> Project:
    p = db.get(Project, pid)
    if p is None or p.owner != user:
        raise HTTPException(404, "Project not found.")
    return p


def audit(db: Session, p: Project, user: str, action: str, **detail) -> None:
    db.add(AuditEvent(project_id=p.id, actor=user, action=action, detail=detail))


# --- ingest / analyze --------------------------------------------------------


def ingest(name: str, data: bytes, plan_file: dict) -> RawPlan:
    low = name.lower()
    try:
        if low.endswith(".dxf"):
            return load_dxf(data, unit_scale=plan_file.get("unit_scale_override"))
        if low.endswith(".pdf"):
            cal = plan_file.get("calibration")
            return load_pdf(
                data,
                page=int(plan_file.get("page") or 0),
                calibration=Calibration(**cal) if cal else None,
                scale_ratio=plan_file.get("scale_ratio"),
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not read {name}: {exc}") from exc
    raise HTTPException(415, "Upload a DXF or PDF floor plan.")


def load_raw(db: Session, user: str, p: Project) -> tuple[RawPlan, PlanGeometry]:
    if not p.plan_file:
        raise HTTPException(409, "Upload a floor plan first.")
    data = storage.load(db, user, p.plan_file["ref"])
    raw = ingest(p.plan_file["name"], data, p.plan_file)
    return raw, build_geometry(raw)


def analyze(db: Session, user: str, p: Project) -> None:
    raw, geom = load_raw(db, user, p)
    p.plan_file = {**p.plan_file, "unit_scale": raw.unit_scale, "ingest_warnings": raw.warnings}
    if not geom.outline:
        p.geometry = {**geom.to_dict(), "view": None}
        p.detection = DetectionResult([], "none", []).to_dict()
    else:
        _, view = render_background(raw, geom)
        result = run_detection(raw, geom)
        p.geometry = {**geom.to_dict(), "view": view}
        p.detection = result.to_dict()
    # A new drawing invalidates the old review and result.
    p.review = {}
    p.result = None
    p.result_at = None
    audit(db, p, user, "analyzed", file=p.plan_file["name"], candidates=len(geom.candidates),
          detector=p.detection["detector"])


def rescale(p: Project, factor: float) -> dict:
    """Plan settings that multiply the current drawing scale by `factor`
    (from 'these two points are really X m apart')."""
    pf = p.plan_file
    new = pf["unit_scale"] * factor
    if pf["name"].lower().endswith(".pdf"):
        return {"scale_ratio": new / PT_TO_M_PAPER, "calibration": None}
    return {"unit_scale_override": new}


def background_png(db: Session, user: str, p: Project) -> bytes:
    raw, geom = load_raw(db, user, p)
    return render_background(raw, geom)[0]


# --- compute -------------------------------------------------------------------


def suppliers_for(db: Session, user: str) -> list[Supplier]:
    own = db.scalars(select(SupplierRow).where(SupplierRow.owner == user).order_by(SupplierRow.created_at)).all()
    return [Supplier.model_validate(r.data) for r in own] + list(demo_suppliers())


def compute(db: Session, user: str, p: Project) -> dict:
    if not p.geometry or not p.detection:
        raise HTTPException(409, "Upload and analyze a floor plan first.")
    if not p.inputs:
        raise HTTPException(409, "Enter the project details (floors, floor height, workforce) first.")
    try:
        inputs = ProjectInputs.model_validate(p.inputs)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid project details: {exc}") from exc

    geom = PlanGeometry.from_dict(p.geometry)
    dets = [Detection(**d) for d in p.detection["detections"]]
    rev = p.review or {}
    try:
        feats = build_features(geom, dets, rev.get("types"), set(rev.get("protected_edges", [])), rev.get("added"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    parsed = ParsedInstructions.model_validate(p.instructions) if p.instructions else None
    if parsed is None and p.instructions_text.strip():
        raise HTTPException(409, "Confirm how your written instructions were understood first.")
    plan = plan_project(feats, inputs, suppliers_for(db, user), "", None, parsed or ParsedInstructions())

    result = {
        **plan.to_dict(),
        "features": [f.to_dict() for f in feats],
        "instructions_confirmed": p.instructions_confirmed or not p.instructions_text.strip(),
        "detector": p.detection["detector"],
    }
    p.result = result
    p.result_at = datetime.now(timezone.utc)
    rec = result["recommendation"]
    if p.selected_supplier not in {b["supplier_id"] for b in rec["baskets"]}:
        p.selected_supplier = rec["best"]
    audit(db, p, user, "computed", best_supplier=rec["best"],
          below_minimum=result["purchase"]["below_minimum"])
    return result


def project_detail(p: Project) -> dict:
    return {
        **p.summary(),
        "inputs": p.inputs,
        "instructions_text": p.instructions_text,
        "instructions": p.instructions,
        "instructions_confirmed": p.instructions_confirmed,
        "plan_file": p.plan_file,
        "geometry": p.geometry,
        "detection": p.detection,
        "review": p.review or {},
        "result": p.result,
        "result_at": p.result_at.isoformat() if p.result_at else None,
        "selected_supplier": p.selected_supplier,
        "photo_checks": p.photo_checks or [],
    }


# --- supplier import mapping suggestions -----------------------------------------

COLUMN_HINTS = [
    ("sku_code", r"\b(sku|code|item\s*code|product\s*code|part)\b"),
    ("pack_qty", r"\b(qty|quantity|pack|pcs|per\s*pack|uom\s*qty)\b"),
    ("price", r"\b(price|rate|mrp|cost|amount|rs|inr)\b"),
    ("brand", r"\b(brand|make|manufacturer|mfr)\b"),
    ("specs", r"\b(spec|standard|is\s*code|certif\w*|bis)\b"),
    ("in_stock", r"\b(stock|availability|available)\b"),
    ("lead_time_days", r"\b(lead|delivery|days)\b"),
    ("kit", r"\b(kit|contents|components)\b"),
    ("item", r"\b(category|item|type|group|class)\b"),
    ("name", r"\b(name|desc\w*|product|particulars)\b"),
]


def preview_price_list(data: bytes, filename: str) -> dict:
    try:
        rows = _read_rows(data, filename)
    except Exception as exc:
        raise HTTPException(422, f"Could not read price list: {exc}") from exc
    headers = list(rows[0].keys()) if rows else []
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for h in headers:
        low = h.strip().lower()
        if low in FIELDS and low not in used:
            mapping[h] = low
            used.add(low)
            continue
        for field, rx in COLUMN_HINTS:
            if field not in used and re.search(rx, low):
                mapping[h] = field
                used.add(field)
                break
    item_col = next((h for h, f in mapping.items() if f == "item"), None)
    name_col = next((h for h, f in mapping.items() if f == "name"), None)
    values = sorted({(r.get(item_col) or "").strip() for r in rows if item_col} - {""})
    suggestions = {}
    for v in values:
        g = guess_item(v.lower())
        if g == GUARDRAIL_SYSTEM:
            g = "guardrail_top_rail_m"
        suggestions[v] = g
    return {
        "headers": headers,
        "sample": rows[:5],
        "rows": len(rows),
        "suggested_columns": mapping,
        "item_values": values,
        "suggested_items": suggestions,
        "item_column": item_col,
        "name_column": name_col,
    }
