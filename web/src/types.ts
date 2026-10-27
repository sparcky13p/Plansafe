// Shapes returned by the PlanSafe API (see safetyplan/server/app.py).

export type Pt = [number, number];
export type HazardType = "stair" | "lift_shaft" | "duct_shaft" | "floor_opening" | "balcony" | "other";

export interface Candidate {
  id: string;
  source: string;
  polygon: Pt[];
  area: number;
  perimeter: number;
  min_dim: number;
  max_dim: number;
  texts: string[];
  blocks: string[];
  layers: string[];
  on_outline: boolean;
  protrudes: boolean;
}

export interface Edge {
  id: string;
  p1: Pt;
  p2: Pt;
  length: number;
  facing: string;
}

export interface View {
  minx: number;
  maxy: number;
  k: number;
  margin: number;
  width: number;
  height: number;
}

export interface Geometry {
  outline: Pt[];
  outline_area: number;
  outline_perimeter: number;
  edges: Edge[];
  candidates: Candidate[];
  warnings: string[];
  view: View | null;
}

export interface Detection {
  candidate_id: string;
  type: HazardType;
  confidence: number;
  source: string;
  needs_review: boolean;
  heuristic_type: HazardType | null;
  muse_type: HazardType | null;
  evidence: string[];
  reason: string;
}

export interface AddedFeature {
  id: string;
  type: HazardType;
  polygon: Pt[];
}

export interface Review {
  types?: Record<string, string>;
  protected_edges?: string[];
  added?: AddedFeature[];
}

export interface Inputs {
  floors: number;
  floor_height: number;
  workforce: number;
  workers_at_height: number | null;
  floors_concurrent: number;
  spare: number;
  packs: string[];
  max_cover_span: number;
  post_spacing: number;
}

export interface Instruction {
  kind: string;
  n: number;
  quote: string;
  [field: string]: unknown;
}

export interface Parsed {
  instructions: Instruction[];
  notes: string[];
  parser: string;
  warnings: string[];
}

export interface TraceEntry {
  rule_id: string;
  pack: string;
  citation: string;
  summary: string;
  verified: boolean;
  feature_id: string;
  feature_type: string;
  edge_ids: string[];
  formula: string;
  inputs: Record<string, number>;
  qty: number;
  governing: boolean;
  facing: string;
}

export interface Requirement {
  item: string;
  name: string;
  unit: string;
  category: string;
  qty: number;
  min_spec: string[];
  verified: boolean;
  trace: TraceEntry[];
}

export interface PlanLine {
  item: string;
  name: string;
  unit: string;
  category: string;
  rule_min: number;
  required: number;
  on_hand: number;
  to_buy: number;
  below_minimum: boolean;
  verified: boolean;
  flags: string[];
  instructions: number[];
}

export interface Applied {
  n: number;
  kind: string;
  quote: string;
  effect: string;
}

export interface BasketLine {
  sku_code: string;
  name: string;
  brand: string;
  pack: string;
  packs: number;
  unit_price: number;
  line_total: number;
  provides: Record<string, number>;
  in_stock: boolean;
}

export interface Basket {
  supplier_id: string;
  supplier_name: string;
  lines: BasketLine[];
  coverage: { item: string; need: number; supplied: number; excess: number }[];
  gaps: { item: string; need: number; reason: string }[];
  total: number;
  excluded_noncompliant: string[];
  warnings: string[];
  coverage_ratio: number;
}

export interface Feature {
  id: string;
  type: string;
  length: number;
  perimeter: number;
  area: number;
  min_dim: number;
  max_dim: number;
  edge_ids: string[];
  facing: string;
}

export interface Result {
  inputs: Inputs & { derived: Record<string, number> };
  requirements: Requirement[];
  skipped: { rule_id: string; feature_id: string; reason: string }[];
  instructions: Parsed;
  purchase: {
    lines: PlanLine[];
    applied: Applied[];
    rejected: Applied[];
    notes: string[];
    brand_pref: string[];
    budget: number | null;
    below_minimum: string[];
  };
  recommendation: {
    best: string | null;
    baskets: Basket[];
    buy_elsewhere: { item: string; need: number; reason: string; alternative: { supplier_name: string; total: number } | null }[];
    budget: number | null;
    over_budget_by: number | null;
  };
  features: Feature[];
  instructions_confirmed: boolean;
  detector: string;
}

export interface PhotoCheck {
  photo: string;
  floor: number | null;
  at: string;
  model: string;
  findings: { feature_id: string; feature_type: string; status: string; detail: string }[];
}

export interface PlanFile {
  name: string;
  size: number;
  unit_scale?: number;
  scale_ratio?: number | null;
  ingest_warnings?: string[];
  pdf?: { pages: { detected_scale: number | null; vector_paths: number; images: number }[] } | null;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string | null;
  has_plan: boolean;
  has_result: boolean;
  inputs: Partial<Inputs>;
  instructions_text: string;
  instructions: Parsed | null;
  instructions_confirmed: boolean;
  plan_file: PlanFile | null;
  geometry: Geometry | null;
  detection: { detector: string; detections: Detection[]; warnings: string[] } | null;
  review: Review;
  result: Result | null;
  result_at: string | null;
  selected_supplier: string | null;
  photo_checks: PhotoCheck[];
}

export interface Me {
  user: string;
  auth_mode: "clerk" | "dev";
  services: { database: string; blob_uploads: boolean; vision_model: string; photo_check: boolean };
}

export interface GenericItem {
  name: string;
  unit: string;
  category: string;
  min_spec: string[];
}
