import { MouseEvent, useRef } from "react";
import type { AddedFeature, Detection, Geometry, Pt } from "../types";
import { HAZARD_COLOUR } from "../util";

export type Mode = "select" | "draw" | "calibrate";

interface Props {
  geometry: Geometry;
  background: string | null;
  detections: Record<string, Detection>;
  types: Record<string, string>; // effective type per candidate (after review)
  typesOverride?: Record<string, string>; // reviewer decisions: these lose the "?" marker
  protectedEdges: Set<string>;
  added: AddedFeature[];
  selected: string | null;
  highlight: Set<string>;
  mode: Mode;
  draft: Pt[]; // points being drawn / calibration points (world coords)
  zoom: number;
  onSelect: (id: string | null) => void;
  onToggleEdge: (id: string) => void;
  onPoint: (p: Pt) => void;
}

export function PlanViewer(p: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const v = p.geometry.view!;
  const px = ([x, y]: Pt): Pt => [(x - v.minx) * v.k + v.margin, (v.maxy - y) * v.k + v.margin];
  const world = (sx: number, sy: number): Pt => [(sx - v.margin) / v.k + v.minx, v.maxy - (sy - v.margin) / v.k];
  const pts = (poly: Pt[]) => poly.map((q) => px(q).join(",")).join(" ");
  const labelSize = Math.max(14, v.width / 70);

  function svgPoint(e: MouseEvent): Pt | null {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return [pt.x, pt.y];
  }

  function onClick(e: MouseEvent) {
    if (p.mode === "select") {
      if (e.target === svgRef.current || (e.target as Element).tagName === "image") p.onSelect(null);
      return;
    }
    const s = svgPoint(e);
    if (s) p.onPoint(world(s[0], s[1]));
  }

  const interactive = p.mode === "select";

  return (
    <div className={`viewer ${p.mode !== "select" ? "drawing" : ""}`}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${v.width} ${v.height}`}
        width={v.width * p.zoom}
        height={v.height * p.zoom}
        onClick={onClick}
        role="img"
        aria-label="Floor plan with detected hazards"
      >
        {p.background ? (
          <image href={p.background} x={0} y={0} width={v.width} height={v.height} />
        ) : (
          <rect width={v.width} height={v.height} fill="#fff" />
        )}

        {p.geometry.edges.map((e) => {
          const prot = p.protectedEdges.has(e.id);
          const hl = p.highlight.has(e.id) || p.selected === e.id;
          const [a, b] = [px(e.p1), px(e.p2)];
          return (
            <g key={e.id} style={{ cursor: interactive ? "pointer" : undefined }}
               onClick={interactive ? (ev) => { ev.stopPropagation(); p.onSelect(e.id); } : undefined}>
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="transparent" strokeWidth={18} vectorEffect="non-scaling-stroke" />
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                stroke={hl ? "#1c7ed6" : prot ? "#2b8a3e" : "#e03131"}
                strokeWidth={hl ? 8 : 5} strokeDasharray={prot ? "10 6" : undefined}
                vectorEffect="non-scaling-stroke" />
            </g>
          );
        })}

        {p.geometry.candidates.map((c) => {
          const t = p.types[c.id] ?? "other";
          const colour = HAZARD_COLOUR[t] ?? "#868e96";
          const det = p.detections[c.id];
          const check = det?.needs_review && !(c.id in (p.typesOverride ?? {}));
          const hl = p.highlight.has(c.id) || p.selected === c.id;
          const [lx, ly] = px(centroid(c.polygon));
          return (
            <g key={c.id} style={{ cursor: interactive ? "pointer" : undefined }}
               onClick={interactive ? (ev) => { ev.stopPropagation(); p.onSelect(c.id); } : undefined}>
              <polygon points={pts(c.polygon)} fill={t === "other" ? "rgba(134,142,150,0.08)" : hexA(colour, 0.22)}
                stroke={hl ? "#1c7ed6" : colour} strokeWidth={hl ? 5 : t === "other" ? 1.5 : 3}
                strokeDasharray={t === "other" || check ? "8 5" : undefined} vectorEffect="non-scaling-stroke" />
              <Label x={lx} y={ly} size={labelSize} text={check ? `${c.id} ?` : c.id} colour={hl ? "#1c7ed6" : colour} />
            </g>
          );
        })}

        {p.added.map((a) => {
          const colour = HAZARD_COLOUR[a.type];
          const hl = p.highlight.has(a.id) || p.selected === a.id;
          const [lx, ly] = px(centroid(a.polygon));
          return (
            <g key={a.id} style={{ cursor: interactive ? "pointer" : undefined }}
               onClick={interactive ? (ev) => { ev.stopPropagation(); p.onSelect(a.id); } : undefined}>
              <polygon points={pts(a.polygon)} fill={hexA(colour, 0.25)} stroke={hl ? "#1c7ed6" : colour}
                strokeWidth={hl ? 5 : 3} vectorEffect="non-scaling-stroke" />
              <Label x={lx} y={ly} size={labelSize} text={a.id} colour={colour} />
            </g>
          );
        })}

        {p.draft.length > 0 && (
          <g pointerEvents="none">
            <polyline points={pts(p.draft)} fill="none" stroke="#1c7ed6" strokeWidth={3} strokeDasharray="6 4"
              vectorEffect="non-scaling-stroke" />
            {p.draft.map((q, i) => {
              const [x, y] = px(q);
              return <circle key={i} cx={x} cy={y} r={6 / p.zoom} fill="#1c7ed6" />;
            })}
          </g>
        )}
      </svg>
    </div>
  );
}

function Label({ x, y, size, text, colour }: { x: number; y: number; size: number; text: string; colour: string }) {
  const w = text.length * size * 0.62 + 8;
  return (
    <g pointerEvents="none">
      <rect x={x - w / 2} y={y - size * 0.7} width={w} height={size * 1.4} rx={3} fill="#fff" stroke={colour} />
      <text x={x} y={y + size * 0.35} textAnchor="middle" fontSize={size} fontWeight={700} fill={colour}
        fontFamily="system-ui, sans-serif">{text}</text>
    </g>
  );
}

export function centroid(poly: Pt[]): Pt {
  const n = poly.length;
  return [poly.reduce((s, q) => s + q[0], 0) / n, poly.reduce((s, q) => s + q[1], 0) / n];
}

function hexA(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
