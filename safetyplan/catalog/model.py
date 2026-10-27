"""Supplier catalogue: what can actually be bought, in which packs and kits."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SKU(BaseModel):
    sku_code: str
    name: str
    brand: str = ""
    # What one purchase unit (pack / kit / roll) provides, in generic-item units.
    # Single item pack of 10 helmets: {"helmet": 10}. Kit: several entries.
    provides: dict[str, float]
    price: float = Field(ge=0, description="INR per purchase unit")
    specs: list[str] = Field(default_factory=list, description="standards certified, e.g. IS 2925")
    in_stock: bool = True
    lead_time_days: int | None = None

    @model_validator(mode="after")
    def _non_empty(self):
        if not self.provides or any(q <= 0 for q in self.provides.values()):
            raise ValueError(f"{self.sku_code}: 'provides' must list positive quantities")
        return self

    @property
    def is_kit(self) -> bool:
        return len(self.provides) > 1

    def meets(self, min_spec: list[str]) -> bool:
        have = {_norm(s) for s in self.specs}
        return all(_norm(s) in have for s in min_spec)

    def pack_label(self) -> str:
        if self.is_kit:
            return "kit"
        (item, q), = self.provides.items()
        return f"pack of {q:g}"


class Supplier(BaseModel):
    id: str
    name: str
    city: str = ""
    skus: list[SKU]


def _norm(spec: str) -> str:
    # "IS 2925:1984", "IS-2925", "is2925" -> "IS2925"
    return spec.upper().replace(" ", "").replace("-", "").split(":")[0]
