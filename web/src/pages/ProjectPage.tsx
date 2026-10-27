import { useEffect, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";
import { DetailsForm } from "../components/DetailsForm";
import { InstructionsStep } from "../components/InstructionsStep";
import { PhotoStep } from "../components/PhotoStep";
import { PlanStep } from "../components/PlanStep";
import { ResultsStep } from "../components/ResultsStep";
import type { Inputs, Project } from "../types";
import { errorText } from "../util";

type Tab = "details" | "plan" | "instructions" | "results" | "photos" | "history";

export function ProjectPage({ id }: { id: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [tab, setTab] = useState<Tab>("details");
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Project>(`/api/projects/${id}`)
      .then((p) => {
        setProject(p);
        setTab(p.result ? "results" : p.geometry ? "plan" : p.inputs?.floors ? "plan" : "details");
      })
      .catch((e) => setError(errorText(e)));
  }, [id]);

  if (error) return <div className="alert error">{error}</div>;
  if (!project) return <p className="muted">Loading…</p>;

  async function saveDetails(name: string, inputs: Inputs) {
    try {
      const p = await api<Project>(`/api/projects/${id}`, { method: "PATCH", json: { name, inputs } });
      setProject(p);
      setTab(p.geometry ? "instructions" : "plan");
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function remove() {
    if (!project) return;
    await api(`/api/projects/${id}`, { method: "DELETE" });
    navigate("/");
  }

  const done: Record<Tab, boolean> = {
    details: Boolean(project.inputs?.floors),
    plan: Boolean(project.geometry && Object.keys(project.review ?? {}).length),
    instructions: !project.instructions_text.trim() || project.instructions_confirmed,
    results: Boolean(project.result),
    photos: project.photo_checks.length > 0,
    history: false,
  };
  const tabs: [Tab, string][] = [
    ["details", "1. Details"],
    ["plan", "2. Drawing & review"],
    ["instructions", "3. Instructions"],
    ["results", "4. Equipment & SKUs"],
    ["photos", "Site photos"],
    ["history", "History"],
  ];

  return (
    <>
      <div className="spread" style={{ marginBottom: 8 }}>
        <div>
          <a href="#/" className="small">← Projects</a>
          <h1 style={{ marginTop: 4 }}>{project.name}</h1>
        </div>
        <DeleteButton onConfirm={remove} />
      </div>
      <div className="tabs" role="tablist">
        {tabs.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`${tab === t ? "active" : ""} ${done[t] ? "done" : ""}`}
            onClick={() => { setTab(t); if (t !== "plan") setHighlight(new Set()); }}>
            {label}
          </button>
        ))}
      </div>
      {tab === "details" && <DetailsForm project={project} onSave={saveDetails} />}
      {tab === "plan" && <PlanStep project={project} onProject={setProject} highlight={highlight} />}
      {tab === "instructions" && <InstructionsStep project={project} onProject={setProject} />}
      {tab === "results" && (
        <ResultsStep project={project} onProject={setProject}
          showOnPlan={(ids) => { setHighlight(new Set(ids)); setTab("plan"); }} />
      )}
      {tab === "photos" && <PhotoStep project={project} onProject={setProject} />}
      {tab === "history" && <History id={id} />}
    </>
  );
}

function DeleteButton({ onConfirm }: { onConfirm: () => void }) {
  const [armed, setArmed] = useState(false);
  return armed ? (
    <div className="row small">
      Delete this project?
      <button className="danger" onClick={onConfirm}>Delete</button>
      <button onClick={() => setArmed(false)}>Cancel</button>
    </div>
  ) : (
    <button className="link small danger" onClick={() => setArmed(true)}>Delete project</button>
  );
}

const ACTION_LABEL: Record<string, string> = {
  created: "Project created",
  analyzed: "Drawing read",
  reviewed: "Review saved",
  inputs_changed: "Details changed",
  instructions_confirmed: "Instructions confirmed",
  computed: "Plan calculated",
  supplier_selected: "Supplier selected",
  scale_set: "Scale changed",
  photo_checked: "Photo checked",
};

function History({ id }: { id: string }) {
  const [rows, setRows] = useState<{ at: string; actor: string; action: string; detail: Record<string, unknown> }[] | null>(null);
  useEffect(() => {
    api<typeof rows>(`/api/projects/${id}/audit`).then(setRows);
  }, [id]);
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <div className="card table-wrap">
      <table>
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="small">{new Date(r.at).toLocaleString()}</td>
              <td className="small">{r.actor}</td>
              <td>{ACTION_LABEL[r.action] ?? r.action}</td>
              <td className="small mono muted">{JSON.stringify(r.detail)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
