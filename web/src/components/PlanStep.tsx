import { DragEvent, useEffect, useMemo, useState } from "react";
import { DIRECT_UPLOAD_LIMIT, api, objectUrl, uploadToBlob } from "../api";
import { useAppData } from "../App";
import type { AddedFeature, HazardType, Project, Pt, Review } from "../types";
import { HAZARD_COLOUR, HAZARD_LABEL, HAZARD_TYPES, errorText, qty } from "../util";
import { Mode, PlanViewer } from "./PlanViewer";

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  highlight?: Set<string>;
}

export function PlanStep({ project, onProject, highlight }: Props) {
  const { me } = useAppData();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function uploadFile(file: File) {
    setError(null);
    if (!/\.(dxf|pdf)$/i.test(file.name)) {
      setError("Upload a DXF or PDF floor plan.");
      return;
    }
    try {
      if (file.size > DIRECT_UPLOAD_LIMIT) {
        if (!me?.services.blob_uploads) {
          setError("This file is over 4 MB. Large uploads need Vercel Blob to be configured.");
          return;
        }
        setBusy("Uploading large file…");
        const url = await uploadToBlob(file);
        setBusy("Reading the drawing…");
        onProject(await api<Project>(`/api/projects/${project.id}/plan-file-url`, { json: { url, name: file.name } }));
      } else {
        setBusy("Reading the drawing and finding hazards…");
        const form = new FormData();
        form.append("file", file);
        onProject(await api<Project>(`/api/projects/${project.id}/plan-file`, { form }));
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <Upload hasPlan={!!project.plan_file} name={project.plan_file?.name} busy={busy} onFile={uploadFile} />
      {project.plan_file && project.geometry && (
        <Review project={project} onProject={onProject} highlight={highlight} setError={setError} />
      )}
    </div>
  );
}

function Upload({ hasPlan, name, busy, onFile }: { hasPlan: boolean; name?: string; busy: string | null; onFile: (f: File) => void }) {
  const [over, setOver] = useState(false);
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  };
  return (
    <div className="card">
      <div className={`dropzone ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
           onDragLeave={() => setOver(false)} onDrop={drop}>
        {busy ? (
          <strong>{busy}</strong>
        ) : (
          <>
            <p style={{ margin: "0 0 8px" }}>
              {hasPlan ? <>Current drawing: <strong>{name}</strong>. Drop a new file to replace it.</> : "Drop a floor plan here (DXF or PDF)"}
            </p>
            <label className="button" style={{ display: "inline-flex" }}>
              Choose file
              <input type="file" accept=".dxf,.pdf" hidden onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
            </label>
            <p className="small muted" style={{ marginBottom: 0 }}>
              DXF gives exact measurements. PDFs must be exported from CAD (not scanned); you can check the scale below.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function Review({ project, onProject, highlight, setError }: Props & { setError: (s: string | null) => void }) {
  const geom = project.geometry!;
  const dets = useMemo(
    () => Object.fromEntries((project.detection?.detections ?? []).map((d) => [d.candidate_id, d])),
    [project.detection],
  );
  const [review, setReview] = useState<Required<Review>>(norm(project.review));
  const [dirty, setDirty] = useState(false);
  const [mode, setMode] = useState<Mode>("select");
  const [draft, setDraft] = useState<Pt[]>([]);
  const [drawType, setDrawType] = useState<HazardType>("floor_opening");
  const [selected, setSelected] = useState<string | null>(null);
  const [bg, setBg] = useState<string | null>(null);
  const [zoom, setZoom] = useState(0.6);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setReview(norm(project.review));
    setDirty(false);
  }, [project.review, project.geometry]);

  useEffect(() => {
    let url: string | null = null;
    if (!geom.view) return;
    objectUrl(`/api/projects/${project.id}/background.png?v=${encodeURIComponent(project.updated_at ?? "")}`)
      .then((u) => setBg((url = u)))
      .catch(() => setBg(null));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [project.id, project.plan_file?.name, geom.view?.width, project.plan_file?.unit_scale]);

  const types: Record<string, string> = {};
  for (const c of geom.candidates) types[c.id] = review.types[c.id] ?? dets[c.id]?.type ?? "other";
  const protectedEdges = new Set(review.protected_edges);
  const toCheck = geom.candidates.filter((c) => dets[c.id]?.needs_review && !(c.id in review.types));

  function update(r: Required<Review>) {
    setReview(r);
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    try {
      onProject(await api<Project>(`/api/projects/${project.id}/review`, { method: "PUT", json: review }));
      setDirty(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  function onPoint(pt: Pt) {
    if (mode === "calibrate") setDraft(draft.length >= 2 ? [pt] : [...draft, pt]);
    else setDraft([...draft, pt]);
  }

  function finishDrawing() {
    if (draft.length < 3) return;
    const n = Math.max(0, ...review.added.map((a) => parseInt(a.id.slice(1), 10))) + 1;
    const f: AddedFeature = { id: `U${n}`, type: drawType, polygon: draft };
    update({ ...review, added: [...review.added, f] });
    setDraft([]);
    setMode("select");
    setSelected(f.id);
  }

  if (!geom.view) {
    return (
      <div className="alert warn">
        No slab outline could be found in this drawing.
        {[...(project.plan_file?.ingest_warnings ?? []), ...geom.warnings].map((w) => <div key={w}>{w}</div>)}
      </div>
    );
  }

  const warnings = [...(project.plan_file?.ingest_warnings ?? []), ...geom.warnings, ...(project.detection?.warnings ?? [])];

  return (
    <>
      {warnings.length > 0 && <div className="alert warn small">{warnings.map((w) => <div key={w}>{w}</div>)}</div>}
      <div className="viewer-layout">
        <div className="stack">
          <div className="spread">
            <div className="row">
              {(["select", "draw", "calibrate"] as Mode[]).map((m) => (
                <button key={m} className={`chip ${mode === m ? "on" : ""}`} onClick={() => { setMode(m); setDraft([]); }}>
                  {m === "select" ? "Select" : m === "draw" ? "Draw missing opening" : "Check scale"}
                </button>
              ))}
            </div>
            <div className="row">
              <button className="chip" onClick={() => setZoom(Math.max(0.2, zoom / 1.25))} aria-label="Zoom out">−</button>
              <span className="small muted">{Math.round(zoom * 100)}%</span>
              <button className="chip" onClick={() => setZoom(Math.min(4, zoom * 1.25))} aria-label="Zoom in">+</button>
            </div>
          </div>
          <PlanViewer geometry={geom} background={bg} detections={dets} types={types} typesOverride={review.types}
            protectedEdges={protectedEdges} added={review.added} selected={selected} highlight={highlight ?? new Set()}
            mode={mode} draft={draft} zoom={zoom} onSelect={setSelected}
            onToggleEdge={(id) => toggleEdge(id)} onPoint={onPoint} />
          <Legend />
        </div>
        <aside className="stack">
          <div className="card stack">
            <div className="spread">
              <h3 style={{ margin: 0 }}>Review</h3>
              <button className="primary" onClick={save} disabled={!dirty || saving}>
                {saving ? "Saving…" : dirty ? "Save review" : "Saved"}
              </button>
            </div>
            <p className="small muted" style={{ margin: 0 }}>
              Slab {qty(geom.outline_area)} m², edge {qty(geom.outline_perimeter)} m. Detected by:{" "}
              {project.detection?.detector}. Click a shape or edge to check it.
            </p>
            {toCheck.length > 0 && (
              <div className="small">
                <strong>{toCheck.length} to check:</strong>{" "}
                {toCheck.map((c) => (
                  <button key={c.id} className="link" style={{ marginRight: 8 }} onClick={() => setSelected(c.id)}>{c.id}</button>
                ))}
              </div>
            )}
          </div>
          {mode === "draw" && (
            <div className="card stack">
              <h3>Draw a missing opening</h3>
              <p className="small muted">Click the corners on the plan, then finish.</p>
              <label>
                Type
                <select value={drawType} onChange={(e) => setDrawType(e.target.value as HazardType)}>
                  {HAZARD_TYPES.filter((t) => t !== "other" && t !== "balcony").map((t) => (
                    <option key={t} value={t}>{HAZARD_LABEL[t]}</option>
                  ))}
                </select>
              </label>
              <div className="row">
                <button className="primary" disabled={draft.length < 3} onClick={finishDrawing}>Finish ({draft.length} points)</button>
                <button onClick={() => setDraft([])}>Clear</button>
              </div>
            </div>
          )}
          {mode === "calibrate" && <Calibrate project={project} draft={draft} onProject={onProject} setError={setError} />}
          {mode === "select" && selected && (
            <Selected id={selected} project={project} dets={dets} types={types} review={review} update={update}
              onRemoveAdded={() => { update({ ...review, added: review.added.filter((a) => a.id !== selected) }); setSelected(null); }} />
          )}
        </aside>
      </div>
    </>
  );

  function toggleEdge(id: string) {
    const s = new Set(review.protected_edges);
    s.has(id) ? s.delete(id) : s.add(id);
    update({ ...review, protected_edges: [...s] });
  }
}

function Selected({ id, project, dets, types, review, update, onRemoveAdded }: {
  id: string; project: Project; dets: Record<string, import("../types").Detection>; types: Record<string, string>;
  review: Required<Review>; update: (r: Required<Review>) => void; onRemoveAdded: () => void;
}) {
  const geom = project.geometry!;
  const edge = geom.edges.find((e) => e.id === id);
  const cand = geom.candidates.find((c) => c.id === id);
  const added = review.added.find((a) => a.id === id);

  if (edge) {
    const prot = review.protected_edges.includes(id);
    return (
      <div className="card stack">
        <h3>Edge {id}</h3>
        <p className="small" style={{ margin: 0 }}>{qty(edge.length)} m, facing {edge.facing}</p>
        <label className="row" style={{ color: "var(--text)", gap: 8 }}>
          <input type="checkbox" checked={prot} onChange={() => {
            const s = new Set(review.protected_edges);
            prot ? s.delete(id) : s.add(id);
            update({ ...review, protected_edges: [...s] });
          }} />
          Already protected (permanent wall or parapet ≥ 1 m)
        </label>
        <p className="small muted" style={{ margin: 0 }}>Protected edges need no guardrail or net.</p>
      </div>
    );
  }
  if (added) {
    return (
      <div className="card stack">
        <h3>{id}: drawn by you</h3>
        <label>
          Type
          <select value={added.type} onChange={(e) => update({ ...review, added: review.added.map((a) => a.id === id ? { ...a, type: e.target.value as HazardType } : a) })}>
            {HAZARD_TYPES.filter((t) => t !== "other" && t !== "balcony").map((t) => <option key={t} value={t}>{HAZARD_LABEL[t]}</option>)}
          </select>
        </label>
        <button className="danger" onClick={onRemoveAdded}>Remove</button>
      </div>
    );
  }
  if (!cand) return null;
  const d = dets[id];
  return (
    <div className="card stack">
      <h3>{id}</h3>
      <p className="small" style={{ margin: 0 }}>
        {qty(cand.min_dim)} × {qty(cand.max_dim)} m · {qty(cand.area)} m² · perimeter {qty(cand.perimeter)} m
      </p>
      {d && (
        <div className="small">
          Detected as <strong>{HAZARD_LABEL[d.type]}</strong> ({Math.round(d.confidence * 100)}%, {d.source})
          {d.needs_review && <span className="badge warn" style={{ marginLeft: 6 }}>check</span>}
          <div className="muted">{d.reason}</div>
          {d.evidence.length > 0 && <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{d.evidence.map((e) => <li key={e}>{e}</li>)}</ul>}
        </div>
      )}
      <label>
        This is a…
        <select value={types[id]} onChange={(e) => update({ ...review, types: { ...review.types, [id]: e.target.value } })}>
          {HAZARD_TYPES.map((t) => <option key={t} value={t}>{HAZARD_LABEL[t]}</option>)}
        </select>
      </label>
      {id in review.types && (
        <button className="link small" onClick={() => {
          const t = { ...review.types };
          delete t[id];
          update({ ...review, types: t });
        }}>Undo my change</button>
      )}
    </div>
  );
}

function Calibrate({ project, draft, onProject, setError }: { project: Project; draft: Pt[]; onProject: (p: Project) => void; setError: (s: string | null) => void }) {
  const [real, setReal] = useState("");
  const [busy, setBusy] = useState(false);
  const pdf = project.plan_file?.pdf?.pages?.[0];
  const measured = draft.length === 2 ? Math.hypot(draft[1][0] - draft[0][0], draft[1][1] - draft[0][1]) : null;

  async function apply(body: object) {
    setBusy(true);
    try {
      onProject(await api<Project>(`/api/projects/${project.id}/scale`, { json: body }));
      setReal("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      <h3>Check the scale</h3>
      {pdf && (
        <p className="small" style={{ margin: 0 }}>
          PDF scale used: 1:{Math.round(project.plan_file?.scale_ratio ?? pdf.detected_scale ?? 100)}
          {pdf.detected_scale ? ` (sheet says 1:${pdf.detected_scale})` : " (no scale found on sheet)"}
        </p>
      )}
      <p className="small muted" style={{ margin: 0 }}>
        Click both ends of a dimension you know (e.g. a dimensioned wall), then type its real length.
      </p>
      {measured !== null && (
        <>
          <p className="small" style={{ margin: 0 }}>Measured on plan: <strong>{measured.toFixed(2)} m</strong></p>
          <label>
            Real length (m)
            <input type="number" min={0.1} step={0.01} value={real} onChange={(e) => setReal(e.target.value)} />
          </label>
          <button className="primary" disabled={busy || !(parseFloat(real) > 0)}
            onClick={() => apply({ factor: parseFloat(real) / measured })}>
            {busy ? "Re-reading…" : "Apply and re-read drawing"}
          </button>
          <p className="small muted" style={{ margin: 0 }}>This re-reads the drawing; your review is cleared.</p>
        </>
      )}
      {pdf && (
        <div className="row">
          {[50, 100, 200].map((r) => (
            <button key={r} className="chip" disabled={busy} onClick={() => apply({ scale_ratio: r, calibration: null })}>1:{r}</button>
          ))}
        </div>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      <span><span className="swatch" style={{ background: "#e03131" }} />Open edge</span>
      <span><span className="swatch" style={{ background: "#2b8a3e" }} />Protected edge</span>
      {HAZARD_TYPES.filter((t) => t !== "other").map((t) => (
        <span key={t}><span className="swatch" style={{ background: HAZARD_COLOUR[t] }} />{HAZARD_LABEL[t]}</span>
      ))}
      <span>"?" = please check</span>
    </div>
  );
}

function norm(r: Review): Required<Review> {
  return { types: r?.types ?? {}, protected_edges: r?.protected_edges ?? [], added: r?.added ?? [] };
}
