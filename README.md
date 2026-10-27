# PlanSafe

**From floor plan to a safety equipment purchase list, before work starts.**

PlanSafe reads a building's drawings and tells a construction contractor exactly what fall-protection and safety equipment the project needs, how much of it, and which products to order. Every item shows which safety rule requires it and which part of the drawing it comes from.

---

## Why this exists

A large share of construction site accidents in India are falls: from open slab edges, unguarded balconies, lift shafts, stair openings and holes left in floors. In many of these cases the protection was never there in the first place. Nobody planned guardrails for the slab edge, nobody counted how many hole covers the floor openings needed, and nobody bought enough harnesses for the people working at height.

Large builders have safety departments that do this planning. Small and mid-sized contractors usually don't. Working out a safety equipment list by hand means:

- going through the drawings to find every edge and opening,
- measuring perimeters and opening sizes,
- knowing which Indian and international safety rules apply to each hazard,
- converting all of that into quantities, and
- turning quantities into products that a supplier actually sells.

That takes time and expertise, so it often gets skipped or done roughly. The equipment then gets bought late, in the wrong quantities, or not at all.

PlanSafe automates this planning step, so getting the safety list right is as easy as uploading a drawing.

## What it does

1. **Upload a floor plan.** DXF (CAD) or PDF, plus a few project details: number of floors, floor-to-floor height, workforce size and how many floors are built at the same time.

2. **Add your own instructions (optional).** Write requests in plain English or Hinglish, for example:
   - *"We already have 25 helmets"*
   - *"Use safety nets instead of guardrails on the north face"*
   - *"Add 15% spares"*
   - *"Prefer brand X, budget under ₹2 lakh"*

   PlanSafe shows how it understood each instruction before applying it.

3. **Hazard detection.** An AI vision model (Muse Spark) identifies stairs, lift shafts, ducts, floor openings, balconies and slab edges on the plan. The CAD geometry supplies the exact measurements. The AI only labels regions and never invents a number.

4. **Human review.** The detected hazards are shown on the plan. The contractor or safety officer confirms them, corrects any mistakes, and marks edges that are already protected by walls or parapets.

5. **Rules engine.** Confirmed hazards go through a rules engine built on Indian construction safety rules (BOCW Rules, relevant IS codes) and OSHA construction standards. It produces the required equipment with quantities, for example:
   - metres of guardrail, mid-rail and toe board, and number of posts
   - hole covers by size
   - stair rails and lift-shaft barriers
   - square metres of safety net
   - harnesses, lanyards, lifelines and anchors
   - helmets, safety shoes, vests and gloves
   - signage and first-aid kits

6. **SKU recommendations.** Contractors buy from one main supplier, in packs and kits, not loose pieces. PlanSafe turns the requirement list into a **basket of real SKUs from a supplier's catalogue**, chosen to cover every requirement at the lowest cost with the least waste. It shows:
   - each SKU, the number of packs and the price
   - any excess, e.g. *"30 helmets for 27 needed: sold in packs of 10"*
   - a comparison across suppliers
   - a short "buy elsewhere" list for anything the main supplier doesn't carry

   Products that don't meet the required standard (e.g. a harness not certified to IS 3521) are never recommended.

7. **Reports.** A PDF report for the safety officer to review and sign off, and a purchase-order spreadsheet that can go straight to the supplier.

8. **Site photo check.** Upload site photos during construction. PlanSafe compares them with the plan and flags edges or openings that may still be unprotected, for a person to verify.

## Built for verification, not blind trust

Safety decisions need to be checkable. In PlanSafe, every line can be traced back to its source:

```
SKU in the basket
  └─ requirement it covers        (e.g. 64.0 m of top rail)
       └─ safety rule              (rule ID + citation)
            └─ drawing feature      (highlighted on the plan, with its measured length)
                 └─ contractor instruction, if one changed it
```

A contractor instruction can never quietly reduce protection below what a rule requires. If it does, the line is flagged and shown in the sign-off section of the report.

## Who it's for

- **Small and mid-sized contractors** who need a correct safety equipment list and purchase order without a dedicated safety team.
- **Safety officers and consultants** who want a fast, auditable first draft to check, instead of starting from scratch.
- **Safety equipment suppliers** who want to offer contractors a project-specific kit instead of a generic catalogue.

## Status

PlanSafe is under active development. The plan-reading and geometry foundation is in place, and the features described above are being built.

> PlanSafe is a planning aid. It does not replace a competent safety officer, site inspection, or the legal obligations of the employer under applicable law.
