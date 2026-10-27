"""End-to-end planning: reviewed features + inputs + instructions -> SKU basket.

    parse instructions -> apply input overrides -> evaluate rules
      -> apply instructions (with safety guard) -> recommend SKUs per supplier
"""

from __future__ import annotations

from dataclasses import dataclass

from safetyplan.catalog.model import Supplier
from safetyplan.detect.muse import MuseClient
from safetyplan.instructions.apply import PurchasePlan, apply_input_overrides, apply_instructions
from safetyplan.instructions.parse import parse_instructions
from safetyplan.instructions.schema import ParsedInstructions
from safetyplan.rules.engine import ProjectInputs, RequirementsResult, evaluate_rules
from safetyplan.rules.features import Feature
from safetyplan.sku.recommend import Recommendation, recommend


@dataclass
class ProjectPlan:
    instructions: ParsedInstructions
    requirements: RequirementsResult
    purchase: PurchasePlan
    recommendation: Recommendation

    def to_dict(self) -> dict:
        return {
            "instructions": self.instructions.model_dump(),
            **self.requirements.to_dict(),
            "purchase": self.purchase.to_dict(),
            "recommendation": self.recommendation.to_dict(),
        }


def plan_project(
    features: list[Feature],
    inputs: ProjectInputs,
    suppliers: list[Supplier],
    instructions_text: str = "",
    client: MuseClient | None = None,
    parsed: ParsedInstructions | None = None,
) -> ProjectPlan:
    """Pass `parsed` (the user-confirmed interpretation) to skip re-parsing."""
    parsed = parsed or parse_instructions(instructions_text, client)
    eff_inputs, pre = apply_input_overrides(inputs, parsed)
    reqs = evaluate_rules(features, eff_inputs)
    purchase = apply_instructions(reqs, parsed, pre)
    rec = recommend(purchase.needs, suppliers, purchase.brand_pref or None, purchase.budget)
    return ProjectPlan(parsed, reqs, purchase, rec)
