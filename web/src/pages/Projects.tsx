import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";
import type { Project } from "../types";
import { errorText } from "../util";

type Summary = Pick<Project, "id" | "name" | "created_at" | "updated_at" | "has_plan" | "has_result">;

export function Projects() {
  const [list, setList] = useState<Summary[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Summary[]>("/api/projects").then(setList).catch((e) => setError(errorText(e)));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const p = await api<Project>("/api/projects", { json: { name: name.trim() } });
      navigate(`/p/${p.id}`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="spread" style={{ marginBottom: 16 }}>
        <div>
          <h1>Projects</h1>
          <p className="muted" style={{ margin: 0 }}>
            Upload a floor plan and get the safety equipment it needs, with quantities and supplier SKUs.
          </p>
        </div>
      </div>
      {error && <div className="alert error">{error}</div>}
      <form className="card row" onSubmit={create}>
        <label style={{ flex: 1, minWidth: 220 }}>
          New project name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Shree Residency, Tower B" required />
        </label>
        <button className="primary" style={{ alignSelf: "flex-end" }} disabled={!name.trim()}>
          Create project
        </button>
      </form>
      {list === null ? (
        <p className="muted">Loading…</p>
      ) : list.length === 0 ? (
        <div className="card empty">No projects yet. Create one above to start.</div>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} className="clickable" onClick={() => navigate(`/p/${p.id}`)}>
                  <td>
                    <a href={`#/p/${p.id}`}>{p.name}</a>
                  </td>
                  <td>
                    {p.has_result ? (
                      <span className="badge ok">plan ready</span>
                    ) : p.has_plan ? (
                      <span className="badge warn">drawing uploaded</span>
                    ) : (
                      <span className="badge">new</span>
                    )}
                  </td>
                  <td className="muted small">{new Date(p.updated_at ?? p.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
