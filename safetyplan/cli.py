"""Inspect a plan from the command line.

    python -m safetyplan.cli path/to/plan.dxf [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from safetyplan.detect.muse import client_from_env
from safetyplan.detect.pipeline import detect
from safetyplan.geometry.build import build_geometry
from safetyplan.ingest.dxf import load_dxf
from safetyplan.ingest.render import render_png
from safetyplan.rules.engine import ProjectInputs, evaluate_rules
from safetyplan.rules.features import build_features


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="safetyplan")
    ap.add_argument("plan", help="DXF file")
    ap.add_argument("--json", action="store_true", help="print geometry + detections as JSON")
    ap.add_argument("--png", metavar="OUT", help="write the image sent to the vision model")
    ap.add_argument("--floors", type=int, help="suspended floors; enables the equipment list")
    ap.add_argument("--floor-height", type=float, default=3.0)
    ap.add_argument("--workforce", type=int, default=0)
    ap.add_argument("--concurrent", type=int, default=2, help="floors with open edges at once")
    args = ap.parse_args(argv)

    raw = load_dxf(args.plan)
    geom = build_geometry(raw)
    image = render_png(raw, geom) if geom.outline else None
    if args.png and image:
        with open(args.png, "wb") as f:
            f.write(image)
    result = detect(geom, image, client_from_env())
    labels = {d.candidate_id: d for d in result.detections}
    reqs = None
    if args.floors:
        inp = ProjectInputs(floors=args.floors, floor_height=args.floor_height,
                            workforce=args.workforce, floors_concurrent=args.concurrent)
        reqs = evaluate_rules(build_features(geom, result.detections), inp)

    if args.json:
        out = {"geometry": geom.to_dict(), **result.to_dict(), **(reqs.to_dict() if reqs else {})}
        json.dump(out, sys.stdout, indent=2)
        print()
        return 0

    print(f"Slab outline: {geom.outline_area:.2f} m2, perimeter {geom.outline_perimeter:.2f} m")
    print(f"Edges: {len(geom.edges)}")
    for e in geom.edges:
        print(f"  {e.id:>4}  {e.length:7.2f} m")
    print(f"Candidates: {len(geom.candidates)}  (detector: {result.detector})")
    for c in geom.candidates:
        d = labels[c.id]
        hints = ", ".join(dict.fromkeys(c.texts + c.blocks + c.layers))
        review = "  CHECK" if d.needs_review else ""
        print(
            f"  {c.id:>4}  {d.type:<13} {d.confidence:4.2f} {d.source:<9}"
            f" {c.min_dim:5.2f} x {c.max_dim:5.2f} m {c.area:7.2f} m2  [{hints}]{review}"
        )
    if reqs:
        print("Equipment required:")
        cat = None
        for r in reqs.requirements:
            if r.category != cat:
                cat = r.category
                print(f"  {cat}")
            flag = "" if r.verified else "  (unverified rule)"
            print(f"    {r.name:<48} {r.qty:>7.0f} {r.unit}{flag}")
    for w in geom.warnings + result.warnings:
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
