import { Fragment, useState } from "react";
import { api, download } from "../api";
import { useAppData } from "../App";
import type { Basket, PlanLine, Project, Requirement } from "../types";
import { HAZARD_LABEL, errorText, qty, rupees } from "../util";

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  showOnPlan: (ids: string[]) => void;
}

export function ResultsStep({ project, onProject, showOnPlan }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"basket" | "requirements">("basket");
  const r = project.result;

  async function compute() {
    setBusy(true);
    setError(null);
    try {
      onProject(await api<Project>(`/api/projects/${project.id}/compute`, { json: {} }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const blockers = [];
  if (!project.inputs || !project.inputs.floors) blockers.push("enter the project details");
  if (!project.geometry) blockers.push("upload a drawing");
  if (project.instructions_text.trim() && !project.instructions) blockers.push("interpret your instructions");

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <div className="card spread">
        <div>
          <h2 style={{ margin: 0 }}>Equipment and purchase list</h2>
          <p className="small muted" style={{ margin: 0 }}>
            {r ? `Last calculated ${new Date(project.result_at!).toLocaleString()}` : "Not calculated yet."}
            {blockers.length > 0 && ` To calculate: ${blockers.join(", ")}.`}
          </p>
        </div>
        <div className="row">
          <button className="primary" onClick={compute} disabled={busy || blockers.length > 0}>
            {busy ? "Calculating…" : r ? "Recalculate" : "Calculate"}
          </button>
          {r && (
            <>
              <button onClick={() => download(`/api/projects/${project.id}/report.pdf`, `${project.name}-safety-plan.pdf`).catch((e) => setError(errorText(e)))}>
                PDF report
              </button>
              <button onClick={() => download(`/api/projects/${project.id}/po.xlsx`, `${project.name}-purchase-order.xlsx`).catch((e) => setError(errorText(e)))}>
                Purchase order (Excel)
              </button>
            </>
          )}
        </div>
      </div>

      {r && (
        <>
          <Banners project={project} />
          <div className="tabs">
            <button className={view === "basket" ? "active" : ""} onClick={() => setView("basket")}>Purchase basket</button>
            <button className={view === "requirements" ? "active" : ""} onClick={() => setView("requirements")}>Requirements &amp; rules</button>
          </div>
          {view === "basket" ? (
            <BasketView project={project} onProject={onProject} setError={setError} />
          ) : (
            <Requirements project={project} showOnPlan={showOnPlan} />
          )}
        </>
      )}
    </div>
  );
}

function Banners({ project }: { project: Project }) {
  const r = project.result!;
  const below = r.purchase.lines.filter((l) => l.below_minimum);
  return (
    <>
      {below.length > 0 && (
        <div className="alert error">
          <strong>{below.length} item(s) below the rule minimum</strong> because of your instructions:{" "}
          {below.map((l) => l.name).join(", ")}. The safety officer must accept these in the report sign-off.
        </div>
      )}
      {r.purchase.rejected.length > 0 && (
        <div className="alert warn small">
          {r.purchase.rejected.map((a) => (
            <div key={a.n}>Instruction #{a.n} “{a.quote}” was not applied: {a.effect}</div>
          ))}
        </div>
      )}
      {!r.instructions_confirmed && (
        <div className="alert warn small">Your written instructions were not confirmed before this calculation.</div>
      )}
    </>
  );
}

function BasketView({ project, onProject, setError }: { project: Project; onProject: (p: Project) => void; setError: (s: string) => void }) {
  const { items } = useAppData();
  const rec = project.result!.recommendation;
  const sel = project.selected_supplier ?? rec.best;
  const basket = rec.baskets.find((b) => b.supplier_id === sel) ?? rec.baskets[0];
  if (!basket) return <div className="card empty">No supplier catalogue loaded.</div>;

  async function choose(id: string) {
    try {
      onProject(await api<Project>(`/api/projects/${project.id}/supplier`, { method: "PUT", json: { supplier_id: id } }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const excess = basket.coverage.filter((c) => c.excess > 0);
  return (
    <div className="stack">
      <div className="card">
        <h3>Compare suppliers</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Supplier</th><th className="num">Total</th><th className="num">Items covered</th><th>Missing</th><th /></tr>
            </thead>
            <tbody>
              {rec.baskets.map((b) => (
                <tr key={b.supplier_id} className={b.supplier_id === basket.supplier_id ? "selected" : "clickable"} onClick={() => choose(b.supplier_id)}>
                  <td>
                    {b.supplier_name} {b.supplier_id === rec.best && <span className="badge ok">recommended</span>}
                  </td>
                  <td className="num">{rupees(b.total)}</td>
                  <td className="num">{Math.round(b.coverage_ratio * 100)}%</td>
                  <td className="small muted">{b.gaps.map((g) => items[g.item]?.name ?? g.item).join(", ") || "—"}</td>
                  <td>{b.supplier_id === basket.supplier_id ? <span className="badge">selected</span> : <button className="link small">Select</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="kpis" style={{ marginBottom: 12 }}>
          <Kpi v={rupees(basket.total)} l={`Total from ${basket.supplier_name}`} />
          <Kpi v={String(basket.lines.length)} l="SKU lines" />
          <Kpi v={`${Math.round(basket.coverage_ratio * 100)}%`} l="Items covered" />
          {rec.budget && <Kpi v={rupees(rec.budget)} l={rec.over_budget_by ? `Budget: over by ${rupees(rec.over_budget_by)}` : "Budget: within"} />}
        </div>
        {rec.over_budget_by && basket.supplier_id === rec.best && (
          <div className="alert warn small">Over budget. Safety items are not reduced to fit a budget; review the requirements with your safety officer.</div>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>SKU</th><th>Product</th><th>Brand</th><th>Pack</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Total</th></tr>
            </thead>
            <tbody>
              {basket.lines.map((l) => (
                <tr key={l.sku_code}>
                  <td className="mono">{l.sku_code}</td>
                  <td>
                    {l.name}
                    {!l.in_stock && <span className="badge warn" style={{ marginLeft: 6 }}>out of stock</span>}
                    <div className="small muted">
                      {Object.entries(l.provides).map(([it, q]) => `${qty(q)} ${items[it]?.unit ?? ""} ${items[it]?.name ?? it}`).join(" + ")}
                    </div>
                  </td>
                  <td>{l.brand}</td>
                  <td className="small">{l.pack}</td>
                  <td className="num">{l.packs}</td>
                  <td className="num">{rupees(l.unit_price)}</td>
                  <td className="num">{rupees(l.line_total)}</td>
                </tr>
              ))}
              <tr><td colSpan={6} className="num"><strong>Total</strong></td><td className="num"><strong>{rupees(basket.total)}</strong></td></tr>
            </tbody>
          </table>
        </div>
        {excess.length > 0 && (
          <p className="small muted">
            Bought above need because of pack sizes:{" "}
            {excess.map((c) => `${items[c.item]?.name} +${qty(c.excess)} (${qty(c.supplied)} for ${qty(c.need)})`).join("; ")}
          </p>
        )}
        <BasketNotes basket={basket} />
      </div>

      {basket.gaps.length > 0 && (
        <div className="card">
          <h3>Buy elsewhere</h3>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {basket.gaps.map((g) => {
              const alt = basket.supplier_id === rec.best ? rec.buy_elsewhere.find((e) => e.item === g.item)?.alternative : null;
              return (
                <li key={g.item}>
                  {items[g.item]?.name}: {qty(g.need)} {items[g.item]?.unit} <span className="muted small">({g.reason})</span>
                  {alt && <span className="small"> — cheapest at {alt.supplier_name}: {rupees(alt.total)}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function BasketNotes({ basket }: { basket: Basket }) {
  return (
    <>
      {basket.excluded_noncompliant.length > 0 && (
        <p className="small muted">Not offered because they don't meet the required standard: {basket.excluded_noncompliant.join(", ")}</p>
      )}
      {basket.warnings.map((w) => <p key={w} className="small" style={{ color: "var(--warn)" }}>{w}</p>)}
    </>
  );
}

function Requirements({ project, showOnPlan }: { project: Project; showOnPlan: (ids: string[]) => void }) {
  const r = project.result!;
  const [open, setOpen] = useState<string | null>(null);
  const reqs = Object.fromEntries(r.requirements.map((x) => [x.item, x]));
  let cat = "";

  return (
    <div className="stack">
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>Item</th><th className="num">Rules need</th><th className="num">Planned</th><th className="num">On hand</th>
              <th className="num">To buy</th><th>Unit</th><th>Rule</th>
            </tr>
          </thead>
          <tbody>
            {r.purchase.lines.map((l) => {
              const head = l.category !== cat ? (cat = l.category) : null;
              return (
                <Fragment key={l.item}>
                  {head && <tr className="cat"><td colSpan={7}>{head}</td></tr>}
                  <tr className={`clickable ${l.below_minimum ? "below" : ""} ${open === l.item ? "selected" : ""}`}
                      onClick={() => setOpen(open === l.item ? null : l.item)}>
                    <td>
                      {l.name}
                      {l.flags.map((f) => <div key={f} className="small muted">{f}</div>)}
                    </td>
                    <td className="num">{qty(l.rule_min)}</td>
                    <td className="num">{qty(l.required)}</td>
                    <td className="num">{l.on_hand ? qty(l.on_hand) : ""}</td>
                    <td className="num"><strong>{qty(l.to_buy)}</strong></td>
                    <td>{l.unit}</td>
                    <td>{l.rule_min === 0 ? <span className="badge">added</span> : l.verified ? <span className="badge ok">verified</span> : <span className="badge warn">unverified</span>}</td>
                  </tr>
                  {open === l.item && (
                    <tr><td colSpan={7}><Trace line={l} req={reqs[l.item]} showOnPlan={showOnPlan} /></td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted">
        “Unverified” rules (Indian rule packs and PlanSafe estimates) still need their clause references checked by a
        safety professional. Click a row to see why it is needed.
      </p>
      {r.purchase.notes.length > 0 && (
        <div className="card small"><strong>Your notes:</strong> {r.purchase.notes.join(" · ")}</div>
      )}
    </div>
  );
}

function Trace({ line, req, showOnPlan }: { line: PlanLine; req?: Requirement; showOnPlan: (ids: string[]) => void }) {
  if (!req) return <div className="drawer">Added by your instructions; no rule requires it.</div>;
  const gov = req.trace.filter((t) => t.governing);
  const ids = [...new Set(gov.flatMap((t) => (t.feature_id === "PROJECT" ? [] : [t.feature_id, ...t.edge_ids])))];
  return (
    <div className="drawer">
      <div className="spread">
        <strong>Why {qty(line.rule_min)} {line.unit}?</strong>
        {ids.length > 0 && <button className="link small" onClick={() => showOnPlan(ids)}>Show on plan</button>}
      </div>
      {gov.map((t, i) => (
        <div key={i} className="trace-entry">
          <div>
            <strong>{t.feature_id === "PROJECT" ? "Whole project" : `${t.feature_id} · ${HAZARD_LABEL[t.feature_type] ?? t.feature_type}`}</strong>
            {t.facing && <span className="muted"> ({t.facing})</span>}: <span className="mono">{t.formula}</span> ={" "}
            <strong>{qty(t.qty)}</strong>
          </div>
          <div className="small muted mono">{Object.entries(t.inputs).map(([k, v]) => `${k}=${qty(v)}`).join("  ")}</div>
          <div className="small">
            {t.rule_id} {!t.verified && <span className="badge warn">unverified</span>} — {t.citation}
          </div>
          <div className="small muted">{t.summary}</div>
        </div>
      ))}
      {req.trace.some((t) => !t.governing) && (
        <div className="small muted" style={{ marginTop: 6 }}>
          Also required by: {[...new Set(req.trace.filter((t) => !t.governing).map((t) => t.rule_id))].join(", ")} (same or smaller quantity; not double-counted).
        </div>
      )}
      {req.min_spec.length > 0 && <div className="small" style={{ marginTop: 6 }}>Products must meet: {req.min_spec.join(", ")}</div>}
    </div>
  );
}

function Kpi({ v, l }: { v: string; l: string }) {
  return <div className="kpi"><div className="v">{v}</div><div className="l">{l}</div></div>;
}
