"""PDF report for the safety officer: plan, requirements, SKU basket,
contractor instructions, rule trace and a sign-off block."""

from __future__ import annotations

from datetime import datetime

import pymupdf

from safetyplan.rules.engine import generic_items

A4 = pymupdf.paper_rect("a4")
M = 40  # margin
FONT, BOLD = "helv", "hebo"
GREY = (0.45, 0.45, 0.45)
RED = (0.75, 0.1, 0.1)
INK = (0.1, 0.1, 0.1)


class _Writer:
    def __init__(self, title: str):
        self.doc = pymupdf.open()
        self.title = title
        self.page = None
        self.y = 0.0
        self.new_page()

    @property
    def width(self) -> float:
        return A4.width - 2 * M

    def new_page(self):
        self.page = self.doc.new_page(width=A4.width, height=A4.height)
        self.page.insert_text((M, 24), f"PlanSafe | {self.title}", fontname=FONT, fontsize=8, color=GREY)
        self.page.insert_text((A4.width - M - 30, A4.height - 20), f"{len(self.doc)}", fontname=FONT,
                              fontsize=8, color=GREY)
        self.y = M

    def need(self, h: float):
        if self.y + h > A4.height - M:
            self.new_page()

    def text(self, s: str, size=9.5, bold=False, color=INK, indent=0.0, gap=3.0):
        font = BOLD if bold else FONT
        lines = _wrap(s, font, size, self.width - indent)
        for line in lines:
            self.need(size + 2)
            self.page.insert_text((M + indent, self.y + size), line, fontname=font, fontsize=size, color=color)
            self.y += size + 2.5
        self.y += gap

    def heading(self, s: str, size=14):
        self.need(size + 30)
        self.y += 6
        self.text(s, size=size, bold=True, gap=4)

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float], size=8.0,
              row_colors: list[tuple | None] | None = None):
        total = sum(widths)
        cols = [w / total * self.width for w in widths]

        def draw_row(cells, bold=False, color=INK, fill=None):
            font = BOLD if bold else FONT
            wrapped = [_wrap(str(c), font, size, w - 4) for c, w in zip(cells, cols)]
            h = max(len(w) for w in wrapped) * (size + 2) + 4
            self.need(h)
            if fill:
                self.page.draw_rect(pymupdf.Rect(M, self.y, M + self.width, self.y + h), color=None, fill=fill)
            x = M
            for lines, w in zip(wrapped, cols):
                yy = self.y + size + 1
                for line in lines:
                    self.page.insert_text((x + 2, yy), line, fontname=font, fontsize=size, color=color)
                    yy += size + 2
                x += w
            self.y += h
            self.page.draw_line((M, self.y), (M + self.width, self.y), color=(0.85, 0.85, 0.85), width=0.5)

        draw_row(headers, bold=True, fill=(0.93, 0.93, 0.93))
        for i, r in enumerate(rows):
            c = (row_colors or [None] * len(rows))[i]
            draw_row(r, color=c or INK)
        self.y += 8

    def image(self, png: bytes, max_h: float):
        pix = pymupdf.Pixmap(png)
        w = self.width
        h = w * pix.height / pix.width
        if h > max_h:
            w, h = w * max_h / h, max_h
        self.need(h + 6)
        self.page.insert_image(pymupdf.Rect(M, self.y, M + w, self.y + h), stream=png)
        self.y += h + 8

    def bytes(self) -> bytes:
        return self.doc.tobytes(deflate=True, garbage=3)


def _wrap(s: str, font: str, size: float, width: float) -> list[str]:
    out = []
    for para in str(s).split("\n"):
        words, line = para.split(" "), ""
        for w in words:
            cand = f"{line} {w}".strip()
            if pymupdf.get_text_length(cand, fontname=font, fontsize=size) <= width or not line:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out or [""]


def _rs(v: float) -> str:
    # Helvetica has no rupee glyph; Indian digit grouping.
    s = f"{v:,.0f}"
    n = f"{int(round(v))}"
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"Rs {s}"


def _q(v: float) -> str:
    return f"{v:g}"


def build_report(project: dict, plan_png: bytes | None) -> bytes:
    r = project["result"]
    items = generic_items()
    inputs = r["inputs"]
    derived = inputs.get("derived", {})
    w = _Writer(project["name"])

    w.text("Safety equipment plan", size=20, bold=True, gap=2)
    w.text(f"{project['name']}  |  generated {datetime.now():%d %b %Y %H:%M}", color=GREY, gap=10)
    w.text(
        f"Floors: {inputs['floors']}   Floor height: {inputs['floor_height']} m   "
        f"Floors open at a time: {min(inputs['floors_concurrent'], inputs['floors'])}   "
        f"Workforce: {inputs['workforce']} (at height: {inputs['workers_at_height']})   "
        f"Spares: {inputs['spare'] * 100:.0f}%", size=9)
    w.text(
        f"Rule packs: {', '.join(inputs['packs'])}   Exposed edge: {derived.get('exposed_edge_length', 0):g} m   "
        f"Openings: {derived.get('opening_count', 0)}   Hazard detection: {r.get('detector', '-')}", size=9, gap=6)

    below = r["purchase"]["below_minimum"]
    if below:
        w.text(f"WARNING: {len(below)} item(s) are below the rule minimum because of contractor instructions: "
               f"{', '.join(items[i]['name'] for i in below)}. See sign-off.", bold=True, color=RED)
    if not r.get("instructions_confirmed", True):
        w.text("Note: the contractor's written instructions were not confirmed before this plan was computed.",
               color=RED)

    if plan_png:
        w.heading("Plan")
        w.text("Red: open edges needing protection. Green: edges marked as already protected. "
               "Labels match the feature ids in the trace appendix.", size=8, color=GREY)
        w.image(plan_png, max_h=420)

    w.heading("Equipment required")
    rows, colors = [], []
    for l in r["purchase"]["lines"]:
        rows.append([l["category"], l["name"], _q(l["rule_min"]), _q(l["required"]), _q(l["on_hand"]),
                     _q(l["to_buy"]), l["unit"], "yes" if l["verified"] else "UNVERIFIED",
                     "; ".join(l["flags"])])
        colors.append(RED if l["below_minimum"] else None)
    w.table(["Category", "Item", "Rule min", "Required", "On hand", "To buy", "Unit", "Rule verified", "Notes"],
            rows, [12, 25, 7, 9, 8, 7, 5, 9, 28], row_colors=colors)
    w.text("'Rule verified' = clause and value checked against the source standard. Unverified lines (Indian rule "
           "packs and PlanSafe estimates) must be checked by the safety officer.", size=8, color=GREY)

    rec = r["recommendation"]
    sel = project.get("selected_supplier") or rec["best"]
    basket = next((b for b in rec["baskets"] if b["supplier_id"] == sel), None)
    if basket:
        w.heading(f"Purchase basket: {basket['supplier_name']}")
        w.table(["SKU", "Product", "Brand", "Pack", "Qty", "Unit price", "Total"],
                [[l["sku_code"], l["name"], l["brand"], l["pack"], str(l["packs"]), _rs(l["unit_price"]),
                  _rs(l["line_total"])] for l in basket["lines"]],
                [11, 38, 10, 9, 5, 12, 13])
        w.text(f"Total: {_rs(basket['total'])}   Coverage: {basket['coverage_ratio'] * 100:.0f}% of items",
               bold=True)
        excess = [c for c in basket["coverage"] if c["excess"] > 0]
        if excess:
            w.text("Bought above need because of pack sizes: " + ", ".join(
                f"{items[c['item']]['name']} +{_q(c['excess'])}" for c in excess), size=8, color=GREY)
        if rec.get("over_budget_by"):
            w.text(f"Over the stated budget of {_rs(rec['budget'])} by {_rs(rec['over_budget_by'])}. "
                   "Safety items were not reduced to fit the budget.", color=RED)
        if basket["gaps"]:
            w.text("Not available from this supplier (buy elsewhere):", bold=True)
            for g in basket["gaps"]:
                alt = next((e["alternative"] for e in rec["buy_elsewhere"] if e["item"] == g["item"]), None)
                where = f" - cheapest: {alt['supplier_name']} {_rs(alt['total'])}" if alt else ""
                w.text(f"- {items[g['item']]['name']}: {_q(g['need'])} ({g['reason']}){where}", indent=10)
        for warn in basket["warnings"]:
            w.text(f"! {warn}", color=RED, size=8.5)
        others = [b for b in rec["baskets"] if b["supplier_id"] != sel]
        if others:
            w.text("Other suppliers compared:", bold=True)
            for b in others:
                w.text(f"- {b['supplier_name']}: {_rs(b['total'])}, {b['coverage_ratio'] * 100:.0f}% of items",
                       indent=10)

    ins = r["instructions"]
    p = r["purchase"]
    if ins.get("instructions") or ins.get("notes"):
        w.heading("Contractor instructions")
        for a in p["applied"]:
            w.text(f"#{a['n']} \"{a['quote']}\" -> {a['effect']}")
        for a in p["rejected"]:
            w.text(f"#{a['n']} \"{a['quote']}\" -> NOT APPLIED: {a['effect']}", color=RED)
        for n in p["notes"]:
            w.text(f"Note: \"{n}\"", color=GREY)

    w.heading("Trace: why each item is required")
    for req in r["requirements"]:
        w.text(f"{req['name']} - {_q(req['qty'])} {req['unit']}", bold=True, gap=1)
        for t in req["trace"]:
            if not t["governing"]:
                continue
            ins_txt = ", ".join(f"{k}={v:g}" for k, v in t["inputs"].items())
            edges = f" edges {','.join(t['edge_ids'])}" if t["edge_ids"] and t["feature_id"] not in t["edge_ids"] else ""
            w.text(f"{t['feature_id']} ({t['feature_type']}{edges}): {t['formula']} [{ins_txt}] = {t['qty']:g}"
                   f"  |  {t['rule_id']}{'' if t['verified'] else ' (unverified)'}  |  {t['citation']}",
                   size=7.5, indent=10, gap=0)
        w.y += 4

    w.heading("Sign-off")
    if below:
        w.text("The following items are below the rule minimum because of contractor instructions. "
               "The safety officer must accept or reject each:", bold=True, color=RED)
        for l in p["lines"]:
            if l["below_minimum"]:
                w.text(f"- {l['name']}: rules require {_q(l['rule_min'])}, plan has {_q(l['required'])}. "
                       f"{'; '.join(l['flags'])}   Accepted [ ]  Rejected [ ]", indent=10)
    w.text("I have checked the hazards identified on the drawing, the quantities above and the rules they come "
           "from, and confirm this plan is suitable for the site.", gap=20)
    for label in ("Safety officer name", "Signature", "Date"):
        w.need(30)
        w.page.insert_text((M, w.y + 10), f"{label}:", fontname=FONT, fontsize=9.5)
        w.page.draw_line((M + 110, w.y + 12), (M + 320, w.y + 12), color=GREY, width=0.5)
        w.y += 26
    w.text("PlanSafe is a planning aid. It does not replace a competent safety officer, site inspection, or the "
           "employer's legal obligations under applicable law.", size=7.5, color=GREY)
    return w.bytes()
