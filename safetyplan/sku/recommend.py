"""Turn equipment needs into a basket of purchasable SKUs per supplier.

Per supplier, choose how many of each pack/kit to buy so every need is
covered, minimising (cost, excess units, packs). Kits couple several items,
so kit counts are searched explicitly (exhaustive when small, local search
otherwise) and the remaining need of each item is covered with single-item
packs by an exact min-cost "cover at least N" dynamic programme.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from safetyplan.catalog.model import SKU, Supplier
from safetyplan.rules.engine import generic_items

RES = 10  # quantity resolution: 0.1 unit (2.5 m panels, 0.5 m2 ...)
MAX_KIT_COMBOS = 5000
INF = (math.inf, math.inf, math.inf)


@dataclass
class BasketLine:
    sku_code: str
    name: str
    brand: str
    pack: str
    packs: int
    unit_price: float
    line_total: float
    provides: dict[str, float]  # total units of each item from this line
    in_stock: bool = True


@dataclass
class Coverage:
    item: str
    need: float
    supplied: float
    excess: float


@dataclass
class Gap:
    item: str
    need: float
    reason: str


@dataclass
class Basket:
    supplier_id: str
    supplier_name: str
    lines: list[BasketLine]
    coverage: list[Coverage]
    gaps: list[Gap]
    total: float
    excluded_noncompliant: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        n = len(self.coverage) + len(self.gaps)
        return len(self.coverage) / n if n else 1.0

    def to_dict(self) -> dict:
        return {**asdict(self), "coverage_ratio": round(self.coverage_ratio, 3)}


@dataclass
class Recommendation:
    best: str | None
    baskets: list[Basket]  # ranked, best first
    buy_elsewhere: list[dict]  # gaps of the best basket + cheapest other source
    budget: float | None = None
    over_budget_by: float | None = None

    def to_dict(self) -> dict:
        return {
            "best": self.best,
            "baskets": [b.to_dict() for b in self.baskets],
            "buy_elsewhere": self.buy_elsewhere,
            "budget": self.budget,
            "over_budget_by": self.over_budget_by,
        }


def recommend(
    needs: dict[str, float],
    suppliers: list[Supplier],
    brand_pref: list[str] | None = None,
    budget: float | None = None,
) -> Recommendation:
    needs = {i: q for i, q in needs.items() if q > 0}
    baskets = [build_basket(needs, s, brand_pref) for s in suppliers]
    baskets.sort(key=lambda b: (-b.coverage_ratio, b.total))
    best = baskets[0] if baskets else None

    elsewhere = []
    if best:
        for g in best.gaps:
            alt = _cheapest_elsewhere(g.item, g.need, suppliers, best.supplier_id)
            elsewhere.append({"item": g.item, "need": g.need, "reason": g.reason, "alternative": alt})

    over = None
    if best and budget is not None and best.total > budget:
        over = round(best.total - budget, 2)
    return Recommendation(best.supplier_id if best else None, baskets, elsewhere, budget, over)


def build_basket(needs: dict[str, float], supplier: Supplier, brand_pref: list[str] | None = None) -> Basket:
    items = generic_items()
    warnings: list[str] = []

    compliant, noncompliant = [], []
    for s in supplier.skus:
        ok = all(s.meets(items[i].get("min_spec", [])) for i in s.provides if i in items)
        (compliant if ok else noncompliant).append(s)
    relevant = [s for s in compliant if any(i in needs for i in s.provides)]

    if brand_pref:
        prefs = {b.strip().lower() for b in brand_pref}
        preferred_items = {i for s in relevant if s.brand.lower() in prefs for i in s.provides}
        relevant = [
            s for s in relevant
            if s.brand.lower() in prefs or not any(i in preferred_items for i in s.provides)
        ]

    # In-stock first; out-of-stock SKUs only for items nothing in stock covers.
    in_stock = [s for s in relevant if s.in_stock]
    covered_in_stock = {i for s in in_stock for i in s.provides}
    backorder = [s for s in relevant if not s.in_stock and any(
        i in needs and i not in covered_in_stock for i in s.provides)]
    pool = in_stock + backorder
    for s in backorder:
        warnings.append(f"{s.sku_code} is out of stock; confirm lead time with the supplier.")

    coverable = {i for s in pool for i in s.provides}
    gaps = []
    for i, q in needs.items():
        if i in coverable:
            continue
        has_any = any(i in s.provides for s in supplier.skus)
        reason = "only non-compliant products listed" if has_any else "not stocked by this supplier"
        gaps.append(Gap(i, q, reason))
    solve_needs = {i: q for i, q in needs.items() if i in coverable}

    counts = _solve(solve_needs, pool)
    by_code = {s.sku_code: s for s in pool}

    lines: list[BasketLine] = []
    supplied: dict[str, float] = {}
    for code, n in counts.items():
        s = by_code[code]
        if n <= 0:
            continue
        prov = {i: q * n for i, q in s.provides.items()}
        for i, q in prov.items():
            supplied[i] = supplied.get(i, 0) + q
        lines.append(BasketLine(s.sku_code, s.name, s.brand, s.pack_label(), n, s.price,
                                round(s.price * n, 2), prov, s.in_stock))
    lines.sort(key=lambda l: l.sku_code)

    coverage = [
        Coverage(i, q, round(supplied.get(i, 0), 3), round(supplied.get(i, 0) - q, 3))
        for i, q in solve_needs.items()
    ]
    return Basket(
        supplier.id, supplier.name, lines, coverage, gaps,
        round(sum(l.line_total for l in lines), 2),
        sorted(s.sku_code for s in noncompliant if any(i in needs for i in s.provides)),
        warnings,
    )


# --- optimisation -------------------------------------------------------------


def _solve(needs: dict[str, float], pool: list[SKU]) -> dict[str, int]:
    """Return sku_code -> number of packs/kits to buy."""
    need_u = {i: _units(q) for i, q in needs.items()}
    kits = [s for s in pool if s.is_kit]
    singles_by_item: dict[str, list[SKU]] = {}
    for s in pool:
        if not s.is_kit:
            (i,) = s.provides
            if i in need_u:
                singles_by_item.setdefault(i, []).append(s)

    @lru_cache(maxsize=None)
    def cover(item: str, r: int):
        """Best single-pack cover of at least r units: (cost, units, packs), {code: n}."""
        return _cover_dp(r, singles_by_item.get(item, []))

    def evaluate(counts: tuple[int, ...]):
        cost = excess = packs = 0.0
        got: dict[str, int] = {}
        for k, n in zip(kits, counts):
            cost += k.price * n
            packs += n
            for i, q in k.provides.items():
                got[i] = got.get(i, 0) + _units(q) * n
        chosen: dict[str, int] = {}
        for i, nu in need_u.items():
            residual = max(0, nu - got.get(i, 0))
            (c, u, p), pick = cover(i, residual)
            if c == math.inf:
                return INF, {}
            cost += c
            packs += p
            excess += got.get(i, 0) + u - nu
            for s, n in pick.items():
                chosen[s] = chosen.get(s, 0) + n
        # Kit components the project does not need are pure excess.
        excess += sum(v for i, v in got.items() if i not in need_u)
        return (round(cost, 2), excess, packs), chosen

    bounds = [
        max((math.ceil(need_u[i] / _units(q)) for i, q in k.provides.items() if i in need_u), default=0)
        for k in kits
    ]
    if math.prod(b + 1 for b in bounds) <= MAX_KIT_COMBOS:
        best = min(
            (evaluate(c) + (c,) for c in itertools.product(*(range(b + 1) for b in bounds))),
            key=lambda t: t[0],
        )
    else:
        best = _local_search(evaluate, bounds)
    _, chosen, counts = best
    for k, n in zip(kits, counts):
        if n:
            chosen[k.sku_code] = n
    return chosen


def _local_search(evaluate, bounds):
    counts = [0] * len(bounds)
    score, chosen = evaluate(tuple(counts))
    improved = True
    while improved:
        improved = False
        for k in range(len(counts)):
            for step in (1, -1):
                c = list(counts)
                c[k] += step
                if not 0 <= c[k] <= bounds[k]:
                    continue
                s, ch = evaluate(tuple(c))
                if s < score:
                    counts, score, chosen, improved = c, s, ch, True
    return score, chosen, tuple(counts)


def _cover_dp(r: int, skus: list[SKU]):
    if r <= 0:
        return (0.0, 0, 0), {}
    if not skus:
        return INF, {}
    packs = [(_units(next(iter(s.provides.values()))), s) for s in skus]
    best: list[tuple] = [(0.0, 0, 0)] + [INF] * r
    back: list[tuple[int, str] | None] = [None] * (r + 1)
    for q in range(1, r + 1):
        for size, s in packs:
            prev = best[max(0, q - size)]
            cand = (prev[0] + s.price, prev[1] + size, prev[2] + 1)
            if cand < best[q]:
                best[q], back[q] = cand, (max(0, q - size), s.sku_code)
    pick: dict[str, int] = {}
    q = r
    while q > 0:
        q, s = back[q]
        pick[s] = pick.get(s, 0) + 1
    c, u, p = best[r]
    return (round(c, 2), u, p), pick


def _units(q: float) -> int:
    return int(round(q * RES))


def _cheapest_elsewhere(item: str, need: float, suppliers: list[Supplier], exclude: str) -> dict | None:
    best = None
    for sup in suppliers:
        if sup.id == exclude:
            continue
        b = build_basket({item: need}, sup)
        if b.gaps:
            continue
        if best is None or b.total < best["total"]:
            best = {"supplier_id": sup.id, "supplier_name": sup.name, "total": b.total,
                    "lines": [asdict(l) for l in b.lines]}
    return best
