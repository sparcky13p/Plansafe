import { FormEvent, useState } from "react";
import type { Inputs, Project } from "../types";
import { PACKS } from "../util";

const DEFAULTS: Inputs = {
  floors: 4,
  floor_height: 3.0,
  workforce: 40,
  workers_at_height: null,
  floors_concurrent: 2,
  spare: 0.1,
  packs: PACKS.map((p) => p.id),
  max_cover_span: 1.5,
  post_spacing: 2.4,
};

export function DetailsForm({ project, onSave }: { project: Project; onSave: (name: string, inputs: Inputs) => Promise<void> }) {
  const [name, setName] = useState(project.name);
  const [v, setV] = useState<Inputs>({ ...DEFAULTS, ...project.inputs } as Inputs);
  const [busy, setBusy] = useState(false);
  const fresh = !project.inputs || Object.keys(project.inputs).length === 0;

  const num = (k: keyof Inputs, int = false) => ({
    value: v[k] === null || v[k] === undefined ? "" : String(v[k]),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setV({ ...v, [k]: e.target.value === "" ? null : int ? parseInt(e.target.value, 10) : parseFloat(e.target.value) }),
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await onSave(name, v);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Project details</h2>
      {fresh && <p className="muted small">Typical values are filled in. Change them to match this site.</p>}
      <label>
        Project name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <div className="grid2">
        <label>
          Floors to be built above ground
          <input type="number" min={1} step={1} required {...num("floors", true)} />
        </label>
        <label>
          Floor-to-floor height (m)
          <input type="number" min={0.5} max={10} step={0.05} required {...num("floor_height")} />
        </label>
        <label>
          Total workforce on site
          <input type="number" min={0} step={1} required {...num("workforce", true)} />
        </label>
        <label>
          Workers at height (leave blank for 40%)
          <input type="number" min={0} step={1} {...num("workers_at_height", true)} />
        </label>
        <label>
          Floors with open edges at the same time
          <input type="number" min={1} step={1} required {...num("floors_concurrent", true)} />
        </label>
        <label>
          Spare PPE (%)
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={Math.round(v.spare * 100)}
            onChange={(e) => setV({ ...v, spare: (parseFloat(e.target.value) || 0) / 100 })}
          />
        </label>
      </div>
      <fieldset style={{ border: "none", padding: 0 }}>
        <legend className="small muted">Rule packs</legend>
        <div className="row">
          {PACKS.map((p) => (
            <label key={p.id} className="row" style={{ gap: 6, color: "var(--text)" }}>
              <input
                type="checkbox"
                checked={v.packs.includes(p.id)}
                onChange={(e) =>
                  setV({ ...v, packs: e.target.checked ? [...v.packs, p.id] : v.packs.filter((x) => x !== p.id) })
                }
              />
              {p.label}
            </label>
          ))}
        </div>
        <p className="small muted">When several packs require the same thing, the larger quantity is used (stricter wins).</p>
      </fieldset>
      <details>
        <summary className="small">Advanced</summary>
        <div className="grid2" style={{ marginTop: 8 }}>
          <label>
            Largest opening closed with a cover plate (m)
            <input type="number" min={0.3} step={0.1} {...num("max_cover_span")} />
          </label>
          <label>
            Guardrail post spacing (m)
            <input type="number" min={0.5} step={0.1} {...num("post_spacing")} />
          </label>
        </div>
      </details>
      <div>
        <button className="primary" disabled={busy || v.packs.length === 0}>
          {busy ? "Saving…" : "Save details"}
        </button>
      </div>
    </form>
  );
}
