import { useState } from "react";

type Candidate = {
  id: string;
  source: string;
  polygon: [number, number][];
  area: number;
  min_dim: number;
  max_dim: number;
  texts: string[];
  blocks: string[];
  layers: string[];
};

type Geometry = {
  outline: [number, number][];
  outline_area: number;
  outline_perimeter: number;
  candidates: Candidate[];
  warnings: string[];
};

// Run 1 shell: upload a DXF and see the extracted outline + candidates.
// The full review UI arrives in run 6.
export function App() {
  const [geom, setGeom] = useState<Geometry | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setError(null);
    const body = new FormData();
    body.append("file", file);
    const r = await fetch("/api/geometry", { method: "POST", body });
    if (!r.ok) {
      setError((await r.json()).detail ?? r.statusText);
      return;
    }
    setGeom(await r.json());
  }

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 960, margin: "0 auto", padding: 16 }}>
      <h1>SafetyPlan</h1>
      <input type="file" accept=".dxf" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {geom && (
        <>
          <p>
            Slab {geom.outline_area.toFixed(1)} m², perimeter {geom.outline_perimeter.toFixed(2)} m,{" "}
            {geom.candidates.length} candidates
          </p>
          <PlanSvg geom={geom} />
        </>
      )}
    </main>
  );
}

function PlanSvg({ geom }: { geom: Geometry }) {
  const xs = geom.outline.map((p) => p[0]);
  const ys = geom.outline.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = 1;
  const pts = (poly: [number, number][]) => poly.map(([x, y]) => `${x},${-y}`).join(" ");
  return (
    <svg
      viewBox={`${minX - pad} ${-maxY - pad} ${maxX - minX + 2 * pad} ${maxY - minY + 2 * pad}`}
      style={{ width: "100%", border: "1px solid #ccc", background: "#fff" }}
    >
      <polygon points={pts(geom.outline)} fill="#eef" stroke="#224" strokeWidth={0.08} />
      {geom.candidates.map((c) => (
        <g key={c.id}>
          <polygon points={pts(c.polygon)} fill="rgba(255,140,0,0.25)" stroke="#c60" strokeWidth={0.05} />
          <text x={c.polygon[0][0] + 0.1} y={-c.polygon[0][1] - 0.1} fontSize={0.4}>
            {c.id}
          </text>
        </g>
      ))}
    </svg>
  );
}
