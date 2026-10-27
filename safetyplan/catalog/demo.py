"""Seeded demo catalogues (fictional suppliers and brands)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from safetyplan.catalog.importer import import_price_list
from safetyplan.catalog.model import Supplier

HERE = Path(__file__).parent

# Supplier B ships its own column names and categories; this is what the
# mapping wizard would produce for it.
SUPPLIER_B_COLUMNS = {
    "Product Code": "sku_code", "Description": "name", "Make": "brand", "Category": "item",
    "Qty per pack": "pack_qty", "Rate (Rs)": "price", "Standard": "specs", "Stock": "in_stock",
}
SUPPLIER_B_ITEMS = {
    "Guardrail post": "guardrail_post", "Top rail": "guardrail_top_rail_m", "Mid rail": "guardrail_mid_rail_m",
    "Toe board": "toe_board_m", "Cover 1m": "hole_cover_1m", "Cover 1.5m": "hole_cover_1_5m",
    "Harness": "full_body_harness", "Lanyard": "lanyard_double", "Helmet": "helmet", "Shoes": "safety_shoes",
    "Vest": "reflective_vest", "Gloves": "gloves_pair", "Sign": "danger_sign",
}


@lru_cache(maxsize=None)
def demo_suppliers() -> tuple[Supplier, ...]:
    a = import_price_list(HERE / "demo_supplier_a.csv", "demo-a", "BuildSafe Depot (demo)")
    b = import_price_list(HERE / "demo_supplier_b.csv", "demo-b", "SiteGuard Traders (demo)",
                          columns=SUPPLIER_B_COLUMNS, item_aliases=SUPPLIER_B_ITEMS)
    for r in (a, b):
        if r.errors:
            raise ValueError(f"demo catalogue {r.supplier.id} has errors: {r.errors}")
    return (a.supplier, b.supplier)
