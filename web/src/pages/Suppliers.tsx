import { useEffect, useState } from "react";
import { api } from "../api";
import { useAppData } from "../App";
import { errorText, rupees } from "../util";

interface SupplierRow {
  id: string;
  name: string;
  skus: number;
  own: boolean;
  errors: string[];
}

interface Preview {
  headers: string[];
  sample: Record<string, string>[];
  rows: number;
  suggested_columns: Record<string, string>;
  item_values: string[];
  suggested_items: Record<string, string | null>;
  item_column: string | null;
}

interface SupplierDetail {
  id: string;
  name: string;
  skus: { sku_code: string; name: string; brand: string; provides: Record<string, number>; price: number; specs: string[]; in_stock: boolean }[];
}

const OUR_FIELDS: [string, string][] = [
  ["", "— ignore —"],
  ["sku_code", "SKU code *"],
  ["name", "Product name *"],
  ["price", "Price (₹) *"],
  ["item", "Category / item type"],
  ["pack_qty", "Quantity per pack"],
  ["brand", "Brand"],
  ["specs", "Standards (IS codes)"],
  ["in_stock", "In stock"],
  ["lead_time_days", "Lead time (days)"],
  ["kit", "Kit contents"],
];

export function Suppliers() {
  const [list, setList] = useState<SupplierRow[] | null>(null);
  const [open, setOpen] = useState<SupplierDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api<SupplierRow[]>("/api/suppliers").then(setList).catch((e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <h1>Suppliers</h1>
      <p className="muted">
        Upload your supplier's price list (CSV or Excel). PlanSafe then builds the purchase basket from products they
        actually sell, in their pack sizes.
      </p>
      {error && <div className="alert error">{error}</div>}
      <ImportWizard onSaved={load} />
      <div className="card table-wrap">
        <h3>Catalogues</h3>
        <table>
          <thead><tr><th>Supplier</th><th className="num">Products</th><th>Import issues</th><th /></tr></thead>
          <tbody>
            {(list ?? []).map((s) => (
              <tr key={s.id}>
                <td>
                  <button className="link" onClick={() => api<SupplierDetail>(`/api/suppliers/${s.id}`).then(setOpen)}>{s.name}</button>{" "}
                  {!s.own && <span className="badge">demo</span>}
                </td>
                <td className="num">{s.skus}</td>
                <td className="small muted">{s.errors.length ? `${s.errors.length} row(s) skipped` : "—"}</td>
                <td>
                  {s.own && (
                    <button className="link small danger" onClick={async () => { await api(`/api/suppliers/${s.id}`, { method: "DELETE" }); load(); }}>
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && <CatalogueView s={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ImportWizard({ onSaved }: { onSaved: () => void }) {
  const { items } = useAppData();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [columns, setColumns] = useState<Record<string, string>>({});
  const [aliases, setAliases] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{ skus: number; errors: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(f: File) {
    setFile(f);
    setResult(null);
    setError(null);
    setName(f.name.replace(/\.(csv|xlsx|xlsm)$/i, ""));
    const form = new FormData();
    form.append("file", f);
    try {
      const p = await api<Preview>("/api/suppliers/preview", { form });
      setPreview(p);
      setColumns(p.suggested_columns);
      setAliases(Object.fromEntries(Object.entries(p.suggested_items).filter(([, v]) => v)) as Record<string, string>);
    } catch (e) {
      setError(errorText(e));
    }
  }

  const itemCol = Object.entries(columns).find(([, f]) => f === "item")?.[0];
  const values = itemCol && preview ? [...new Set(preview.sample.map((r) => r[itemCol]).filter(Boolean))] : [];
  const allValues = itemCol === preview?.item_column ? preview?.item_values ?? [] : values;
  const required = ["sku_code", "name", "price"].filter((f) => !Object.values(columns).includes(f));

  async function save() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("supplier_name", name);
      form.append("columns", JSON.stringify(Object.fromEntries(Object.entries(columns).filter(([, v]) => v))));
      form.append("item_aliases", JSON.stringify(aliases));
      setResult(await api<{ skus: number; errors: string[] }>("/api/suppliers", { form }));
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      <h3>Add a price list</h3>
      {error && <div className="alert error">{error}</div>}
      <input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])} />
      {preview && (
        <>
          <label>
            Supplier name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div>
            <strong className="small">1. Match their columns</strong> <span className="small muted">({preview.rows} rows)</span>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Their column</th><th>Means</th><th>Example</th></tr></thead>
                <tbody>
                  {preview.headers.map((h) => (
                    <tr key={h}>
                      <td>{h}</td>
                      <td>
                        <select value={columns[h] ?? ""} onChange={(e) => setColumns({ ...columns, [h]: e.target.value })}>
                          {OUR_FIELDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      </td>
                      <td className="small muted">{preview.sample[0]?.[h]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {required.length > 0 && <p className="small" style={{ color: "var(--danger)" }}>Still needed: {required.join(", ")}</p>}
          </div>
          {itemCol && allValues.length > 0 && (
            <div>
              <strong className="small">2. Match their categories to PlanSafe items</strong>
              <p className="small muted" style={{ margin: 0 }}>Rows left unmatched are skipped and listed after import.</p>
              <div className="grid2" style={{ marginTop: 6 }}>
                {allValues.map((v) => (
                  <label key={v}>
                    {v}
                    <select value={aliases[v] ?? ""} onChange={(e) => setAliases({ ...aliases, [v]: e.target.value })}>
                      <option value="">— not a safety item / skip —</option>
                      {Object.entries(items).map(([id, it]) => <option key={id} value={id}>{it.name}</option>)}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}
          <div>
            <button className="primary" onClick={save} disabled={busy || required.length > 0 || !name.trim()}>
              {busy ? "Importing…" : "Import price list"}
            </button>
          </div>
        </>
      )}
      {result && (
        <div className={`alert ${result.errors.length ? "warn" : "ok"} small`}>
          Imported {result.skus} products.
          {result.errors.length > 0 && (
            <>
              {" "}{result.errors.length} row(s) skipped:
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{result.errors.slice(0, 20).map((e) => <li key={e}>{e}</li>)}</ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function CatalogueView({ s, onClose }: { s: SupplierDetail; onClose: () => void }) {
  const { items } = useAppData();
  return (
    <div className="card">
      <div className="spread"><h3>{s.name}</h3><button className="link" onClick={onClose}>Close</button></div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>SKU</th><th>Product</th><th>Brand</th><th>Provides</th><th>Standards</th><th className="num">Price</th></tr></thead>
          <tbody>
            {s.skus.map((k) => (
              <tr key={k.sku_code}>
                <td className="mono">{k.sku_code}</td>
                <td>{k.name}{!k.in_stock && <span className="badge warn" style={{ marginLeft: 6 }}>out of stock</span>}</td>
                <td>{k.brand}</td>
                <td className="small">{Object.entries(k.provides).map(([it, q]) => `${q} × ${items[it]?.name ?? it}`).join(", ")}</td>
                <td className="small">{k.specs.join(", ") || "—"}</td>
                <td className="num">{rupees(k.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
