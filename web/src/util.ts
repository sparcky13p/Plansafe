import type { HazardType } from "./types";

export const HAZARD_LABEL: Record<string, string> = {
  stair: "Stair",
  lift_shaft: "Lift shaft",
  duct_shaft: "Duct / shaft",
  floor_opening: "Floor opening",
  balcony: "Balcony",
  other: "Not a hazard",
  slab_edge: "Slab edge",
  project: "Whole project",
};

export const HAZARD_COLOUR: Record<string, string> = {
  stair: "#7b3fc8",
  lift_shaft: "#c92a2a",
  duct_shaft: "#e8590c",
  floor_opening: "#d9a400",
  balcony: "#1c7ed6",
  other: "#868e96",
};

export const HAZARD_TYPES: HazardType[] = ["stair", "lift_shaft", "duct_shaft", "floor_opening", "balcony", "other"];

export const PACKS: { id: string; label: string }[] = [
  { id: "osha_1926", label: "OSHA 29 CFR 1926" },
  { id: "is_bocw", label: "BOCW Rules 1998 + IS codes" },
  { id: "site_practice", label: "Site practice (PlanSafe estimates)" },
];

/** Indian digit grouping: 12,34,567 */
export function rupees(v: number): string {
  return "₹" + Math.round(v).toLocaleString("en-IN");
}

export function qty(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
