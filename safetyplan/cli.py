"""Inspect a plan from the command line.

    python -m safetyplan.cli path/to/plan.dxf [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="safetyplan")
    ap.add_argument("plan", help="DXF file")
    ap.add_argument("--json", action="store_true", help="print full geometry as JSON")
    args = ap.parse_args(argv)

    geom = build_geometry(load_dxf(args.plan))
    if args.json:
        json.dump(geom.to_dict(), sys.stdout, indent=2)
        print()
        return 0

    print(f"Slab outline: {geom.outline_area:.2f} m2, perimeter {geom.outline_perimeter:.2f} m")
    print(f"Edges: {len(geom.edges)}")
    for e in geom.edges:
        print(f"  {e.id:>4}  {e.length:7.2f} m")
    print(f"Candidates: {len(geom.candidates)}")
    for c in geom.candidates:
        hints = ", ".join(c.texts + c.blocks + c.layers)
        flags = " ".join(f for f, on in (("on-outline", c.on_outline), ("protrudes", c.protrudes)) if on)
        print(
            f"  {c.id:>4}  {c.source:<12} {c.min_dim:5.2f} x {c.max_dim:5.2f} m"
            f"  {c.area:7.2f} m2  [{hints}] {flags}"
        )
    for w in geom.warnings:
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
