import { useEffect, useState } from "react";
import { api } from "../api";
import { useAppData } from "../App";
import type { Instruction, Parsed, Project } from "../types";
import { errorText } from "../util";

const KIND_LABEL: Record<string, string> = {
  inventory_on_hand: "Already on site",
  substitute: "Replace",
  input_override: "Change project detail",
  brand_pref: "Preferred brand",
  budget_cap: "Budget",
  add_item: "Add extra",
  exclude: "Remove item",
};
const FIELD_LABEL: Record<string, string> = {
  floors: "Floors",
  floor_height: "Floor height (m)",
  workforce: "Workforce",
  workers_at_height: "Workers at height",
  floors_concurrent: "Floors open at a time",
  spare: "Spare fraction (0.15 = 15%)",
};
const FACES = ["north", "east", "south", "west"];
const EXAMPLES = [
  "We already have 25 helmets",
  "North side pe railing ki jagah jaali lagana",
  "15% extra rakhna",
  "Prefer SafeCrest brand, budget 2 lakh",
  "Work only on 3 floors at a time",
];

export function InstructionsStep({ project, onProject }: { project: Project; onProject: (p: Project) => void }) {
  const [text, setText] = useState(project.instructions_text);
  const [draft, setDraft] = useState<Parsed | null>(project.instructions);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(project.instructions);
  }, [project.instructions]);

  const stale = text.trim() !== project.instructions_text.trim() || (text.trim() && !project.instructions);

  async function interpret() {
    setBusy(true);
    setError(null);
    try {
      onProject(await api<Project>(`/api/projects/${project.id}/instructions/parse`, { json: { text } }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      onProject(await api<Project>(`/api/projects/${project.id}/instructions`, { method: "PUT", json: draft }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const edit = (i: number, patch: Partial<Instruction>) =>
    draft && setDraft({ ...draft, instructions: draft.instructions.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const remove = (i: number) => draft && setDraft({ ...draft, instructions: draft.instructions.filter((_, j) => j !== i) });

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <div className="card stack">
        <h2>Your instructions (optional)</h2>
        <p className="small muted" style={{ margin: 0 }}>
          Write anything that should change the list, in English or Hinglish, one point per line. PlanSafe shows how it
          understood each point before using it. Safety items can only be removed with a reason, and the report flags them.
        </p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={EXAMPLES.join("\n")} />
        <div className="row">
          <button className="primary" onClick={interpret} disabled={busy || !text.trim()}>
            {busy ? "Reading…" : "Interpret"}
          </button>
          {stale && project.instructions && <span className="small" style={{ color: "var(--warn)" }}>Text changed; interpret again.</span>}
        </div>
      </div>

      {draft && !stale && (
        <div className="card stack">
          <div className="spread">
            <h2 style={{ margin: 0 }}>We understood</h2>
            {project.instructions_confirmed ? <span className="badge ok">confirmed</span> : <span className="badge warn">not confirmed yet</span>}
          </div>
          {draft.warnings.map((w) => <div key={w} className="alert warn small">{w}</div>)}
          {draft.instructions.length === 0 && <p className="muted">No instructions found in the text.</p>}
          {draft.instructions.map((ins, i) => (
            <InstructionEditor key={i} ins={ins} onChange={(p) => edit(i, p)} onRemove={() => remove(i)} />
          ))}
          {draft.notes.length > 0 && (
            <div className="small">
              <strong>Kept as notes on the report</strong> (not instructions):
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{draft.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>
          )}
          <div>
            <button className="primary" onClick={confirm} disabled={busy}>
              {project.instructions_confirmed ? "Save changes" : "Confirm"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function InstructionEditor({ ins, onChange, onRemove }: { ins: Instruction; onChange: (p: Partial<Instruction>) => void; onRemove: () => void }) {
  const { items } = useAppData();
  const itemOptions = (extra = false) => (
    <>
      {extra && <option value="guardrail_system">Guardrail system (rails, toe boards, posts)</option>}
      {Object.entries(items).map(([id, it]) => <option key={id} value={id}>{it.name}</option>)}
    </>
  );
  const num = (k: string, step = 1) => (
    <input type="number" step={step} min={0} value={String(ins[k] ?? "")}
      onChange={(e) => onChange({ [k]: parseFloat(e.target.value) })} />
  );

  return (
    <div className="instr stack">
      <div className="spread">
        <strong>#{ins.n} {KIND_LABEL[ins.kind] ?? ins.kind}</strong>
        <button className="link small danger" onClick={onRemove}>Don't apply</button>
      </div>
      {ins.quote && <div className="quote small">“{ins.quote}”</div>}
      <div className="grid2">
        {(ins.kind === "inventory_on_hand" || ins.kind === "add_item" || ins.kind === "exclude") && (
          <label>Item<select value={String(ins.item)} onChange={(e) => onChange({ item: e.target.value })}>{itemOptions()}</select></label>
        )}
        {(ins.kind === "inventory_on_hand" || ins.kind === "add_item") && <label>Quantity{num("qty")}</label>}
        {ins.kind === "exclude" && (
          <label>
            Reason (required)
            <input value={String(ins.reason ?? "")} onChange={(e) => onChange({ reason: e.target.value })}
              placeholder="Why is this item not needed?" />
          </label>
        )}
        {ins.kind === "substitute" && (
          <>
            <label>Replace<select value={String(ins.from_item)} onChange={(e) => onChange({ from_item: e.target.value })}>{itemOptions(true)}</select></label>
            <label>With<select value={String(ins.to_item)} onChange={(e) => onChange({ to_item: e.target.value })}>{itemOptions()}</select></label>
            <div>
              <span className="small muted">Sides (none = everywhere)</span>
              <div className="row">
                {FACES.map((f) => {
                  const faces = (ins.faces as string[]) ?? [];
                  const on = faces.includes(f);
                  return (
                    <button key={f} className={`chip ${on ? "on" : ""}`}
                      onClick={() => onChange({ faces: on ? faces.filter((x) => x !== f) : [...faces, f] })}>{f}</button>
                  );
                })}
              </div>
            </div>
          </>
        )}
        {ins.kind === "input_override" && (
          <>
            <label>Detail<select value={String(ins.field)} onChange={(e) => onChange({ field: e.target.value })}>
              {Object.entries(FIELD_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></label>
            <label>New value{num("value", 0.01)}</label>
          </>
        )}
        {ins.kind === "brand_pref" && (
          <label>Brands (comma separated)
            <input value={((ins.brands as string[]) ?? []).join(", ")}
              onChange={(e) => onChange({ brands: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
          </label>
        )}
        {ins.kind === "budget_cap" && <label>Budget (₹){num("amount_inr", 1000)}</label>}
      </div>
      {ins.kind === "exclude" && !String(ins.reason ?? "").trim() && (
        <div className="small" style={{ color: "var(--danger)" }}>Without a reason this will not be applied.</div>
      )}
    </div>
  );
}
