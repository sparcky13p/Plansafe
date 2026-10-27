"""HTTP API.

Stateless endpoints (/api/geometry, /api/detect, /api/plan ...) run the
pipeline on an uploaded file in one call. The project endpoints
(/api/projects/...) persist each step for the web app.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from safetyplan.catalog.demo import demo_suppliers
from safetyplan.catalog.importer import import_price_list
from safetyplan.config import settings
from safetyplan.db.models import AuditEvent, Project, SupplierRow, get_session
from safetyplan.detect.pipeline import detect
from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf
from safetyplan.ingest.pdf import pdf_info
from safetyplan.ingest.render import render_png, render_report_png
from safetyplan.instructions.parse import parse_instructions
from safetyplan.instructions.schema import ParsedInstructions
from safetyplan.models import HAZARD_TYPES, PlanGeometry, RawPlan
from safetyplan.photo.sam import SamError, check_photo, sam_from_env
from safetyplan.plan import plan_project
from safetyplan.report.pdf import build_report
from safetyplan.report.xlsx import build_po
from safetyplan.rules.engine import ProjectInputs, evaluate_rules, generic_items
from safetyplan.rules.features import build_features, feature_from_polygon
from safetyplan.server import service, storage
from safetyplan.server.auth import current_user

app = FastAPI(title="PlanSafe API", version="0.5.0")

# Vercel caps request bodies at 4.5 MB; larger plans go through Blob.
MAX_DIRECT_UPLOAD = 4 * 1024 * 1024


def db_session() -> Iterator[Session]:
    db = get_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- meta ----------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/me")
def me(user: str = Depends(current_user)) -> dict:
    s = settings()
    muse = service.muse_client()
    return {
        "user": user,
        "auth_mode": s.auth_mode,
        "services": {
            "database": "postgres" if s.database_url.startswith("postgresql") else "sqlite",
            "blob_uploads": bool(s.blob_token),
            "vision_model": muse.name if muse else "drawing labels only",
            "photo_check": bool(sam_from_env()),
        },
    }


@app.get("/api/catalog/items")
def catalog_items() -> dict:
    return {"items": generic_items(), "hazard_types": list(HAZARD_TYPES)}


# --- projects --------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    inputs: dict | None = None
    instructions_text: str = ""


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    inputs: dict | None = None
    instructions_text: str | None = None


class AddedFeature(BaseModel):
    id: str = Field(pattern=r"^U\d+$")
    type: str
    polygon: list[tuple[float, float]] = Field(min_length=3)


class Review(BaseModel):
    """Reviewer corrections from the plan viewer."""

    types: dict[str, str] = {}  # candidate id -> hazard type ("other" drops it)
    protected_edges: list[str] = []
    added: list[AddedFeature] = []


class PlanFileUrl(BaseModel):
    url: str
    name: str


class ScaleSettings(BaseModel):
    page: int | None = Field(None, ge=0)
    scale_ratio: float | None = Field(None, gt=0)
    calibration: dict | None = None  # {x1, y1, x2, y2, distance_m} in PDF points
    factor: float | None = Field(None, gt=0, description="multiply the current scale (two-point calibration)")


class InstructionText(BaseModel):
    text: str


class SupplierChoice(BaseModel):
    supplier_id: str


@app.get("/api/projects")
def list_projects(user: str = Depends(current_user), db: Session = Depends(db_session)) -> list[dict]:
    rows = db.scalars(select(Project).where(Project.owner == user).order_by(Project.updated_at.desc())).all()
    return [p.summary() for p in rows]


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectCreate, user: str = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    inputs = _valid_inputs(body.inputs) if body.inputs else {}
    p = Project(owner=user, name=body.name, inputs=inputs, instructions_text=body.instructions_text)
    db.add(p)
    db.flush()
    service.audit(db, p, user, "created", name=body.name)
    return service.project_detail(p)


@app.get("/api/projects/{pid}")
def get_project(pid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    return service.project_detail(service.get_project(db, user, pid))


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch, user: str = Depends(current_user),
                  db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    if body.name is not None:
        p.name = body.name
    if body.inputs is not None:
        p.inputs = _valid_inputs(body.inputs)
        service.audit(db, p, user, "inputs_changed", inputs=p.inputs)
    if body.instructions_text is not None and body.instructions_text != p.instructions_text:
        p.instructions_text = body.instructions_text
        p.instructions, p.instructions_confirmed = None, False
    p.updated_at = datetime.now(timezone.utc)
    return service.project_detail(p)


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> Response:
    p = service.get_project(db, user, pid)
    for e in db.scalars(select(AuditEvent).where(AuditEvent.project_id == p.id)):
        db.delete(e)
    db.delete(p)
    return Response(status_code=204)


@app.post("/api/projects/{pid}/plan-file")
async def upload_plan(pid: str, file: UploadFile, page: int = Form(0), scale_ratio: float | None = Form(None),
                      user: str = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    name = file.filename or "plan"
    _check_plan_name(name)
    data = await file.read()
    if len(data) > MAX_DIRECT_UPLOAD:
        raise HTTPException(413, "File too large for direct upload; use the large-file upload.")
    ref = storage.save(db, user, name, data, file.content_type or "application/octet-stream")
    p.plan_file = {"name": name, "ref": ref, "size": len(data), "page": page, "scale_ratio": scale_ratio,
                   "calibration": None, "pdf": pdf_info(data) if name.lower().endswith(".pdf") else None}
    service.analyze(db, user, p)
    return service.project_detail(p)


@app.post("/api/projects/{pid}/plan-file-url")
def plan_from_blob(pid: str, body: PlanFileUrl, user: str = Depends(current_user),
                   db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    _check_plan_name(body.name)
    storage.check_blob_url(body.url)
    data = storage.load(db, user, body.url)
    p.plan_file = {"name": body.name, "ref": body.url, "size": len(data), "page": 0, "scale_ratio": None,
                   "calibration": None, "pdf": pdf_info(data) if body.name.lower().endswith(".pdf") else None}
    service.analyze(db, user, p)
    return service.project_detail(p)


@app.post("/api/projects/{pid}/scale")
def set_scale(pid: str, body: ScaleSettings, user: str = Depends(current_user),
              db: Session = Depends(db_session)) -> dict:
    """PDF calibration: re-read the drawing with a new page / scale."""
    p = service.get_project(db, user, pid)
    if not p.plan_file:
        raise HTTPException(409, "Upload a floor plan first.")
    changes = body.model_dump(exclude_unset=True)
    factor = changes.pop("factor", None)
    if factor:
        changes.update(service.rescale(p, factor))
    p.plan_file = {**p.plan_file, **changes}
    service.analyze(db, user, p)
    service.audit(db, p, user, "scale_set", **changes, factor=factor)
    return service.project_detail(p)


@app.get("/api/projects/{pid}/background.png")
def background(pid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> Response:
    p = service.get_project(db, user, pid)
    return Response(service.background_png(db, user, p), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@app.put("/api/projects/{pid}/review")
def put_review(pid: str, body: Review, user: str = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    if not p.geometry:
        raise HTTPException(409, "Upload a floor plan first.")
    cids = {c["id"] for c in p.geometry["candidates"]}
    eids = {e["id"] for e in p.geometry["edges"]}
    bad = [k for k in body.types if k not in cids] + [e for e in body.protected_edges if e not in eids]
    bad += [t for t in body.types.values() if t not in HAZARD_TYPES]
    if bad:
        raise HTTPException(422, f"Unknown ids or types in review: {bad}")
    for a in body.added:
        try:
            feature_from_polygon(a.id, a.type, a.polygon)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    old = p.review or {}
    p.review = body.model_dump()
    service.audit(db, p, user, "reviewed", changes=_review_diff(old, p.review))
    return service.project_detail(p)


@app.post("/api/projects/{pid}/instructions/parse")
def parse_project_instructions(pid: str, body: InstructionText, user: str = Depends(current_user),
                               db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    parsed = parse_instructions(body.text, service.muse_client())
    p.instructions_text = body.text
    p.instructions = parsed.model_dump()
    p.instructions_confirmed = False
    return service.project_detail(p)


@app.put("/api/projects/{pid}/instructions")
def confirm_instructions(pid: str, body: ParsedInstructions, user: str = Depends(current_user),
                         db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    p.instructions = body.numbered().model_dump()
    p.instructions_confirmed = True
    service.audit(db, p, user, "instructions_confirmed",
                  instructions=[{"n": i.n, "kind": i.kind, "quote": i.quote} for i in body.instructions])
    return service.project_detail(p)


@app.post("/api/projects/{pid}/compute")
def compute(pid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    service.compute(db, user, p)
    return service.project_detail(p)


@app.put("/api/projects/{pid}/supplier")
def choose_supplier(pid: str, body: SupplierChoice, user: str = Depends(current_user),
                    db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    if not p.result or body.supplier_id not in {b["supplier_id"] for b in p.result["recommendation"]["baskets"]}:
        raise HTTPException(422, "Unknown supplier for this plan; compute first.")
    p.selected_supplier = body.supplier_id
    service.audit(db, p, user, "supplier_selected", supplier=body.supplier_id)
    return service.project_detail(p)


@app.get("/api/projects/{pid}/report.pdf")
def report_pdf(pid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> Response:
    p = service.get_project(db, user, pid)
    if not p.result:
        raise HTTPException(409, "Compute the plan first.")
    raw, geom = service.load_raw(db, user, p)
    added = {a["id"]: a["polygon"] for a in (p.review or {}).get("added", [])}
    feats = [{**f, "polygon": added.get(f["id"])} for f in p.result["features"]]
    png = render_report_png(raw, geom, feats) if geom.outline else None
    pdf = build_report(service.project_detail(p), png)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(p.name)}-safety-plan.pdf"'})


@app.get("/api/projects/{pid}/po.xlsx")
def report_xlsx(pid: str, supplier: str | None = None, user: str = Depends(current_user),
                db: Session = Depends(db_session)) -> Response:
    p = service.get_project(db, user, pid)
    if not p.result:
        raise HTTPException(409, "Compute the plan first.")
    try:
        data = build_po(service.project_detail(p), supplier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(p.name)}-purchase-order.xlsx"'})


@app.get("/api/projects/{pid}/audit")
def project_audit(pid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> list[dict]:
    p = service.get_project(db, user, pid)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.project_id == p.id).order_by(AuditEvent.at)).all()
    return [e.to_dict() for e in rows]


@app.post("/api/projects/{pid}/photos")
async def photo_check(pid: str, file: UploadFile, feature_ids: str = Form(..., description="JSON list"),
                      floor: int | None = Form(None), user: str = Depends(current_user),
                      db: Session = Depends(db_session)) -> dict:
    p = service.get_project(db, user, pid)
    if not p.result:
        raise HTTPException(409, "Compute the plan first.")
    client = sam_from_env()
    if client is None:
        raise HTTPException(503, "Photo check is not configured (needs SAM 3.1 access).")
    try:
        ids = json.loads(feature_ids)
    except ValueError as exc:
        raise HTTPException(422, "feature_ids must be a JSON list") from exc
    feats = [f for f in p.result["features"] if f["id"] in ids]
    if not feats:
        raise HTTPException(422, "Select the edges/openings this photo shows.")
    data = await file.read()
    if len(data) > MAX_DIRECT_UPLOAD:
        raise HTTPException(413, "Photo too large; resize below 4 MB.")
    try:
        findings = check_photo(data, feats, client)
    except SamError as exc:
        raise HTTPException(502, str(exc)) from exc
    ref = storage.save(db, user, file.filename or "photo.jpg", data, file.content_type or "image/jpeg")
    entry = {"photo": file.filename, "ref": ref, "floor": floor, "at": datetime.now(timezone.utc).isoformat(),
             "model": client.name, "findings": [f.__dict__ for f in findings]}
    p.photo_checks = [*(p.photo_checks or []), entry]
    service.audit(db, p, user, "photo_checked", photo=file.filename,
                  flagged=[f.feature_id for f in findings if f.status == "possibly_unprotected"])
    return entry


# --- suppliers ---------------------------------------------------------------------


@app.get("/api/suppliers")
def list_suppliers(user: str = Depends(current_user), db: Session = Depends(db_session)) -> list[dict]:
    own = db.scalars(select(SupplierRow).where(SupplierRow.owner == user).order_by(SupplierRow.created_at)).all()
    out = [{"id": r.id, "name": r.name, "skus": len(r.data["skus"]), "own": True, "errors": r.import_errors}
           for r in own]
    out += [{"id": s.id, "name": s.name, "skus": len(s.skus), "own": False, "errors": []} for s in demo_suppliers()]
    return out


@app.get("/api/suppliers/{sid}")
def get_supplier(sid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    for s in demo_suppliers():
        if s.id == sid:
            return s.model_dump()
    r = db.get(SupplierRow, sid)
    if r is None or r.owner != user:
        raise HTTPException(404, "Supplier not found.")
    return r.data


@app.post("/api/suppliers/preview")
async def preview_supplier(file: UploadFile, user: str = Depends(current_user)) -> dict:
    """Headers, sample rows and suggested column / item mapping for the import wizard."""
    _check_price_list_name(file.filename)
    return service.preview_price_list(await file.read(), file.filename or "list.csv")


@app.post("/api/suppliers", status_code=201)
async def save_supplier(file: UploadFile, supplier_name: str = Form(...), columns: str = Form("{}"),
                        item_aliases: str = Form("{}"), user: str = Depends(current_user),
                        db: Session = Depends(db_session)) -> dict:
    rep = await _import(file, supplier_name, columns, item_aliases)
    sid = f"{_slug(supplier_name)}-{user[-6:]}".lower()
    existing = db.get(SupplierRow, sid)
    if existing and existing.owner != user:
        raise HTTPException(409, "Supplier id clash; choose another name.")
    supplier = rep.supplier.model_copy(update={"id": sid})
    if existing:
        existing.name, existing.data, existing.import_errors = supplier_name, supplier.model_dump(), rep.errors
    else:
        db.add(SupplierRow(id=sid, owner=user, name=supplier_name, data=supplier.model_dump(),
                           import_errors=rep.errors))
    return {"id": sid, "name": supplier_name, "skus": len(supplier.skus), "errors": rep.errors,
            "rows_read": rep.rows_read}


@app.delete("/api/suppliers/{sid}", status_code=204)
def delete_supplier(sid: str, user: str = Depends(current_user), db: Session = Depends(db_session)) -> Response:
    r = db.get(SupplierRow, sid)
    if r is None or r.owner != user:
        raise HTTPException(404, "Supplier not found.")
    db.delete(r)
    return Response(status_code=204)


# --- stateless pipeline endpoints ---------------------------------------------------


@app.post("/api/geometry")
async def geometry(file: UploadFile) -> dict:
    _, geom = await _load(file)
    return geom.to_dict()


@app.post("/api/render", response_class=Response)
async def render(file: UploadFile) -> Response:
    """The PNG that is sent to the vision model, with candidate IDs overlaid."""
    raw, geom = await _load(file)
    return Response(render_png(raw, geom), media_type="image/png")


@app.post("/api/detect")
async def detect_hazards(file: UploadFile) -> dict:
    raw, geom = await _load(file)
    result = _detect(raw, geom)
    return {"geometry": geom.to_dict(), **result.to_dict()}


@app.post("/api/requirements")
async def requirements(
    file: UploadFile,
    inputs: str = Form(..., description="ProjectInputs as JSON"),
    review: str = Form("{}", description="Review as JSON"),
) -> dict:
    inp, rev = _parse_inputs_review(inputs, review)
    raw, geom = await _load(file)
    det = _detect(raw, geom)
    feats = build_features(geom, det.detections, rev.types, set(rev.protected_edges),
                           [a.model_dump() for a in rev.added])
    try:
        result = evaluate_rules(feats, inp)
    except ValueError as exc:  # unknown rule pack
        raise HTTPException(422, str(exc)) from exc
    return {"geometry": geom.to_dict(), **det.to_dict(), "features": [f.to_dict() for f in feats],
            **result.to_dict()}


@app.post("/api/instructions/parse")
def instructions_parse(body: InstructionText) -> dict:
    """Interpretation shown to the contractor to confirm/edit before planning."""
    return parse_instructions(body.text, service.muse_client()).model_dump()


@app.post("/api/suppliers/import")
async def suppliers_import(
    file: UploadFile,
    supplier_name: str = Form(...),
    columns: str = Form("{}", description="their header -> our field, JSON"),
    item_aliases: str = Form("{}", description="their item text -> generic item id, JSON"),
) -> dict:
    rep = await _import(file, supplier_name, columns, item_aliases)
    return {"supplier": rep.supplier.model_dump(), "errors": rep.errors, "rows_read": rep.rows_read}


@app.get("/api/suppliers-demo")
def suppliers_demo() -> list[dict]:
    return [s.model_dump() for s in demo_suppliers()]


@app.post("/api/plan")
async def plan(
    file: UploadFile,
    inputs: str = Form(..., description="ProjectInputs as JSON"),
    review: str = Form("{}", description="Review as JSON"),
    instructions: str = Form("", description="free text (parsed server-side)"),
    confirmed_instructions: str = Form("", description="ParsedInstructions JSON from the confirm step"),
    price_list: UploadFile | None = File(None),
    supplier_name: str = Form("Your supplier"),
) -> dict:
    """Full pipeline: drawing -> hazards -> rules -> instructions -> SKU basket."""
    inp, rev = _parse_inputs_review(inputs, review)
    try:
        parsed = (ParsedInstructions.model_validate(json.loads(confirmed_instructions))
                  if confirmed_instructions else None)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, f"Invalid instructions: {exc}") from exc
    raw, geom = await _load(file)
    det = _detect(raw, geom)
    feats = build_features(geom, det.detections, rev.types, set(rev.protected_edges),
                           [a.model_dump() for a in rev.added])
    suppliers = list(demo_suppliers())
    import_errors: list[str] = []
    if price_list is not None and price_list.filename:
        rep = await _import(price_list, supplier_name, "{}", "{}")
        import_errors = rep.errors
        suppliers.insert(0, rep.supplier)
    try:
        result = plan_project(feats, inp, suppliers, instructions, service.muse_client(), parsed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"geometry": geom.to_dict(), **det.to_dict(), "features": [f.to_dict() for f in feats],
            **result.to_dict(), "price_list_errors": import_errors}


# --- helpers ---------------------------------------------------------------------------


def _valid_inputs(d: dict) -> dict:
    try:
        return ProjectInputs.model_validate(d).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid project details: {exc}") from exc


def _parse_inputs_review(inputs: str, review: str) -> tuple[ProjectInputs, Review]:
    try:
        return ProjectInputs.model_validate(json.loads(inputs)), Review.model_validate(json.loads(review))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, f"Invalid inputs: {exc}") from exc


def _review_diff(old: dict, new: dict) -> dict:
    ot, nt = old.get("types", {}), new.get("types", {})
    return {
        "relabelled": {k: v for k, v in nt.items() if ot.get(k) != v},
        "protected_edges": sorted(set(new.get("protected_edges", [])) ^ set(old.get("protected_edges", []))),
        "added": [a["id"] for a in new.get("added", []) if a["id"] not in {x["id"] for x in old.get("added", [])}],
    }


def _check_plan_name(name: str) -> None:
    if not name.lower().endswith((".dxf", ".pdf")):
        raise HTTPException(415, "Upload a DXF or PDF floor plan.")


def _check_price_list_name(name: str | None) -> None:
    if not (name or "").lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(415, "Price list must be CSV or XLSX.")


async def _import(file: UploadFile, name: str, columns: str, aliases: str):
    try:
        cols, al = json.loads(columns), json.loads(aliases)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid mapping JSON: {exc}") from exc
    _check_price_list_name(file.filename)
    data = await file.read()
    try:
        return import_price_list(data, _slug(name), name, filename=file.filename, columns=cols, item_aliases=al)
    except Exception as exc:
        raise HTTPException(422, f"Could not read price list: {exc}") from exc


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "supplier"


def _fname(name: str) -> str:
    return _slug(name)[:60] or "project"


def _detect(raw: RawPlan, geom: PlanGeometry):
    if not geom.outline:
        return detect(geom, None, None)
    return service.run_detection(raw, geom)


async def _load(file: UploadFile) -> tuple[RawPlan, PlanGeometry]:
    if not (file.filename or "").lower().endswith(".dxf"):
        raise HTTPException(415, "Only DXF is supported here; use a project for PDF plans.")
    data = await file.read()
    if len(data) > MAX_DIRECT_UPLOAD:
        raise HTTPException(413, "File too large for direct upload.")
    try:
        raw = load_dxf(data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read DXF: {exc}") from exc
    return raw, build_geometry(raw)
