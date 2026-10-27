import { useState } from "react";
import { api } from "../api";
import { useAppData } from "../App";
import type { PhotoCheck, Project } from "../types";
import { HAZARD_LABEL, errorText, qty } from "../util";

const STATUS: Record<string, { label: string; cls: string }> = {
  protection_visible: { label: "Protection visible", cls: "ok" },
  possibly_unprotected: { label: "Possibly unprotected", cls: "danger" },
  not_visible: { label: "Not visible in photo", cls: "" },
};

export function PhotoStep({ project, onProject }: { project: Project; onProject: (p: Project) => void }) {
  const { me } = useAppData();
  const [file, setFile] = useState<File | null>(null);
  const [ids, setIds] = useState<string[]>([]);
  const [floor, setFloor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const feats = project.result?.features ?? [];

  if (!project.result) return <div className="card empty">Calculate the plan first, then check site photos against it.</div>;

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("feature_ids", JSON.stringify(ids));
      if (floor) form.append("floor", floor);
      await api<PhotoCheck>(`/api/projects/${project.id}/photos`, { form });
      onProject(await api<Project>(`/api/projects/${project.id}`));
      setFile(null);
      setIds([]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="card stack">
        <h2>Site photo check</h2>
        <p className="small muted" style={{ margin: 0 }}>
          Upload a site photo and tick the edges or openings it shows. PlanSafe looks for each hazard and for
          guardrails, nets or covers next to it. Results are hints to check on site, never a guarantee.
        </p>
        {!me?.services.photo_check && (
          <div className="alert warn small">Photo check needs the SAM 3.1 service, which is not connected yet.</div>
        )}
        {error && <div className="alert error">{error}</div>}
        <div className="grid2">
          <label>
            Photo (JPG/PNG, under 4 MB)
            <input type="file" accept="image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label>
            Floor (optional)
            <input type="number" min={0} value={floor} onChange={(e) => setFloor(e.target.value)} />
          </label>
        </div>
        <div>
          <span className="small muted">What does this photo show?</span>
          <div className="row" style={{ marginTop: 4 }}>
            {feats.map((f) => {
              const on = ids.includes(f.id);
              return (
                <button key={f.id} className={`chip ${on ? "on" : ""}`}
                  onClick={() => setIds(on ? ids.filter((x) => x !== f.id) : [...ids, f.id])}>
                  {f.id} · {HAZARD_LABEL[f.type] ?? f.type}{f.type === "slab_edge" ? ` ${qty(f.length)} m ${f.facing}` : ""}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <button className="primary" disabled={!file || ids.length === 0 || busy || !me?.services.photo_check} onClick={submit}>
            {busy ? "Checking…" : "Check photo"}
          </button>
        </div>
      </div>

      {[...project.photo_checks].reverse().map((c, i) => (
        <div key={i} className="card">
          <div className="spread">
            <strong>{c.photo}{c.floor != null ? ` · floor ${c.floor}` : ""}</strong>
            <span className="small muted">{new Date(c.at).toLocaleString()}</span>
          </div>
          <table>
            <tbody>
              {c.findings.map((f) => (
                <tr key={f.feature_id}>
                  <td>{f.feature_id} · {HAZARD_LABEL[f.feature_type] ?? f.feature_type}</td>
                  <td><span className={`badge ${STATUS[f.status]?.cls ?? ""}`}>{STATUS[f.status]?.label ?? f.status}</span></td>
                  <td className="small">{f.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
