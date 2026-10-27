"""Typed contractor instructions ("we already have 25 helmets" -> InventoryOnHand)."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

FACES = ("north", "east", "south", "west")
# Alias for the whole guardrail system on an edge.
GUARDRAIL_SYSTEM = "guardrail_system"
GUARDRAIL_ITEMS = ("guardrail_top_rail_m", "guardrail_mid_rail_m", "toe_board_m", "guardrail_post")

INPUT_FIELDS = Literal["floors", "floor_height", "workforce", "workers_at_height", "floors_concurrent", "spare"]


class _Base(BaseModel):
    n: int = 0  # 1-based number shown to the user ("instruction #2")
    quote: str = ""  # the contractor's words this came from


class InventoryOnHand(_Base):
    kind: Literal["inventory_on_hand"] = "inventory_on_hand"
    item: str
    qty: float = Field(gt=0)


class Substitute(_Base):
    kind: Literal["substitute"] = "substitute"
    from_item: str  # generic item id or "guardrail_system"
    to_item: str
    faces: list[Literal["north", "east", "south", "west"]] = Field(default_factory=list)  # empty = everywhere
    ratio: float | None = Field(None, gt=0, description="to_item units per from_item unit")


class InputOverride(_Base):
    kind: Literal["input_override"] = "input_override"
    field: INPUT_FIELDS
    value: float = Field(ge=0)


class BrandPref(_Base):
    kind: Literal["brand_pref"] = "brand_pref"
    brands: list[str] = Field(min_length=1)


class BudgetCap(_Base):
    kind: Literal["budget_cap"] = "budget_cap"
    amount_inr: float = Field(gt=0)


class AddItem(_Base):
    kind: Literal["add_item"] = "add_item"
    item: str
    qty: float = Field(gt=0)
    reason: str = ""


class Exclude(_Base):
    kind: Literal["exclude"] = "exclude"
    item: str
    reason: str = ""


Instruction = Annotated[
    Union[InventoryOnHand, Substitute, InputOverride, BrandPref, BudgetCap, AddItem, Exclude],
    Field(discriminator="kind"),
]
INSTRUCTIONS = TypeAdapter(list[Instruction])


class ParsedInstructions(BaseModel):
    instructions: list[Instruction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # text that could not be turned into an instruction
    parser: str = "offline"
    warnings: list[str] = Field(default_factory=list)

    def numbered(self) -> "ParsedInstructions":
        for i, ins in enumerate(self.instructions, 1):
            ins.n = i
        return self
