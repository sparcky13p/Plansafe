"""Free-text contractor instructions -> typed instructions.

Two parsers share one schema:
- parse_offline: deterministic keyword/regex parser for common English and
  Hinglish phrasings. Used when no model is configured, as the fallback when
  the model fails, and as the behaviour of MockMuse in tests.
- Muse Spark: handles phrasings the regexes miss. Output is schema-validated
  and unknown item ids are demoted to notes.

Either way, the user confirms the interpretation before it is applied.
"""

from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from safetyplan.detect.muse import MuseClient, MuseError, _extract_json
from safetyplan.instructions.schema import (
    FACES,
    GUARDRAIL_SYSTEM,
    INSTRUCTIONS,
    AddItem,
    BrandPref,
    BudgetCap,
    Exclude,
    InputOverride,
    InventoryOnHand,
    ParsedInstructions,
    Substitute,
)
from safetyplan.rules.engine import generic_items

PARSER_MARKER = "PLANSAFE_INSTRUCTION_PARSER"

# Longest / most specific first.
ITEM_WORDS: list[tuple[str, str]] = [
    ("first_aid_box", r"first[\s-]?aid(\s*box(es)?|\s*kits?)?"),
    ("lanyard_double", r"lanyards?"),
    ("full_body_harness", r"(full\s*body\s*)?harness(es)?|safety\s*belts?|body\s*belts?"),
    ("lifeline_m", r"life\s*lines?"),
    ("safety_net_m2", r"(safety\s*)?nets?|jaali|jali"),
    (GUARDRAIL_SYSTEM, r"guard\s*rails?|railings?|edge\s*protection"),
    ("helmet", r"helmets?|hard\s*hats?"),
    ("safety_shoes", r"(safety\s*)?shoes?|boots?|joote|jute"),
    ("reflective_vest", r"(reflective\s*|hi[\s-]?vis\s*)?(vests?|jackets?)"),
    ("gloves_pair", r"gloves?|dastane"),
    ("danger_sign", r"(warning\s*|danger\s*|caution\s*)?(signs?|signage|boards?)"),
]
_ITEM_RE = [(item, re.compile(rf"\b({pat})\b", re.I)) for item, pat in ITEM_WORDS]

FACE_WORDS = {"north": "north", "uttar": "north", "south": "south", "dakshin": "south",
              "east": "east", "purab": "east", "poorab": "east", "west": "west", "paschim": "west"}

NUM = r"(\d+(?:\.\d+)?)"


def parse_instructions(text: str, client: MuseClient | None = None) -> ParsedInstructions:
    text = (text or "").strip()
    if not text:
        return ParsedInstructions()
    if client is not None:
        try:
            return _parse_with_model(text, client).numbered()
        except (MuseError, httpx.HTTPError) as exc:
            parsed = parse_offline(text)
            parsed.warnings.append(f"Instruction model unavailable, used built-in parser: {exc}")
            return parsed
    return parse_offline(text)


def parse_offline(text: str) -> ParsedInstructions:
    out = ParsedInstructions(parser="offline")
    for clause in _clauses(text):
        ins = _parse_clause(clause)
        if ins is None:
            out.notes.append(clause)
        else:
            ins.quote = clause
            out.instructions.append(ins)
    return out.numbered()


def _clauses(text: str) -> list[str]:
    t = re.sub(r"\bRs\.?\s*", "Rs ", text)
    # Split on newlines, ';', sentence dots (not decimals) and commas not inside numbers.
    parts = re.split(r"[\n;]+|(?<!\d)\.(?!\d)|(?<!\d),|,(?!\d)", t)
    return [p.strip(" -•*\t") for p in parts if p and p.strip(" -•*\t")]


def _parse_clause(c: str):
    low = c.lower()

    if "budget" in low or "lakh" in low or "crore" in low:
        amt = _amount(low)
        if amt:
            return BudgetCap(amount_inr=amt)

    m = re.search(rf"{NUM}\s*%", low)
    if m and re.search(r"spare|extra|buffer|zyada|jyada|more|additional", low):
        return InputOverride(field="spare", value=float(m.group(1)) / 100)

    m = re.search(rf"{NUM}\s*(floors?|slabs?|manzil|storey|storeys)\b.*?(at a time|ek\s*sath|ek\s*saath|"
                  r"simultaneous|together|concurrent|parallel)", low)
    if m:
        return InputOverride(field="floors_concurrent", value=float(m.group(1)))

    m = re.search(rf"{NUM}\s*(workers|worker|labou?rs?|mazdoor|people|log)\b", low)
    if m:
        field = "workers_at_height" if re.search(r"at height|upar|on (the )?edge|facade", low) else "workforce"
        if field == "workers_at_height" or re.search(r"total|site|workforce|team|hai|have|will|around|approx", low):
            return InputOverride(field=field, value=float(m.group(1)))

    m = re.search(r"([a-z][\w&-]*)\s+(brand|make|company)\b", low) or re.search(
        r"\b(brand|make)\s*[:\-]?\s*([a-z][\w&-]*)", low)
    if m:
        name = m.group(1) if m.group(2) in ("brand", "make", "company") else m.group(2)
        if name not in ("any", "the", "a", "same", "good", "cheap", "local"):
            original = re.search(re.escape(name), c, re.I).group(0)
            return BrandPref(brands=[original])

    sub = _substitution(c, low)
    if sub:
        return sub

    item = _item(low)
    if item and re.search(r"\b(no|not needed|don'?t need|do not need|nahi chahiye|nahin chahiye|mat lo|"
                          r"skip|exclude|remove|without)\b", low):
        reason = ""
        rm = re.search(r"\b(because|kyunki|kyuki|since|as)\b\s*(.+)", c, re.I)
        if rm:
            reason = rm.group(2).strip()
        return Exclude(item=item, reason=reason) if item != GUARDRAIL_SYSTEM else Exclude(
            item="guardrail_top_rail_m", reason=reason)

    qty = re.search(NUM, low)
    if item and qty and item != GUARDRAIL_SYSTEM:
        if re.search(r"\b(already|pehle se|paas|pass|have|has|existing|in stock|stock|hai|hain|available)\b", low):
            return InventoryOnHand(item=item, qty=float(qty.group(1)))
        if re.search(r"\b(add|extra|plus|aur|additional|more)\b", low):
            return AddItem(item=item, qty=float(qty.group(1)), reason=c)
    return None


def _substitution(c: str, low: str):
    m = re.search(r"(.+?)\s+(instead of|in place of|rather than)\s+(.+)", low)
    if m:
        to_txt, from_txt = m.group(1), m.group(3)
    else:
        m = re.search(r"(.+?)\s+(ki jagah|ke jagah|ke badle|ki jagah par)\s+(.+)", low)
        if not m:
            return None
        from_txt, to_txt = m.group(1), m.group(3)
    to_item, from_item = _item(to_txt), _item(from_txt)
    if not to_item or not from_item or to_item == from_item:
        return None
    faces = sorted({FACE_WORDS[w] for w in re.findall(r"\b(" + "|".join(FACE_WORDS) + r")\b", low)},
                   key=FACES.index)
    return Substitute(from_item=from_item, to_item=to_item, faces=faces)


def _item(text: str) -> str | None:
    best = None
    for item, rx in _ITEM_RE:
        m = rx.search(text)
        if m and (best is None or m.start() < best[1]):
            best = (item, m.start())
    return best[0] if best else None


def _amount(low: str) -> float | None:
    m = re.search(rf"{NUM}\s*(lakh|lac|lakhs|crore|cr|k|thousand)\b", low)
    if m:
        mult = {"lakh": 1e5, "lac": 1e5, "lakhs": 1e5, "crore": 1e7, "cr": 1e7, "k": 1e3, "thousand": 1e3}
        return float(m.group(1)) * mult[m.group(2)]
    m = re.search(r"(\d[\d,]{3,})", low)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


# --- model-based parsing --------------------------------------------------------

def system_prompt() -> str:
    items = generic_items()
    vocab = "\n".join(f"- {k}: {v['name']} ({v['unit']})" for k, v in items.items())
    return f"""{PARSER_MARKER}
You turn a construction contractor's free-text instructions (English or Hinglish) into typed
instructions for a safety equipment planner. Never invent instructions that are not in the text.
Item ids (use exactly these; "{GUARDRAIL_SYSTEM}" means the whole guardrail: rails, toe boards, posts):
{vocab}
- {GUARDRAIL_SYSTEM}: complete guardrail system
Instruction kinds:
- inventory_on_hand {{item, qty}}: equipment the contractor already owns
- substitute {{from_item, to_item, faces: [north|east|south|west] (empty = all), ratio (optional)}}
- input_override {{field: floors|floor_height|workforce|workers_at_height|floors_concurrent|spare, value}}
  (spare is a fraction: "15% extra" -> 0.15)
- brand_pref {{brands: [..]}}
- budget_cap {{amount_inr}} ("2 lakh" -> 200000)
- add_item {{item, qty, reason}}
- exclude {{item, reason}} (keep the contractor's reason if given, else empty)
Each instruction also has "quote": the exact words it came from.
Text that is not an instruction goes to "notes".
Respond with JSON only: {{"instructions": [{{"kind": "...", ...}}], "notes": ["..."]}}"""


def _parse_with_model(text: str, client: MuseClient) -> ParsedInstructions:
    known = set(generic_items()) | {GUARDRAIL_SYSTEM}
    last = ""
    for attempt in range(2):
        user = text if attempt == 0 else f"{text}\n\n(Previous answer invalid: {last}. JSON only.)"
        raw = client.complete(system_prompt(), user, None)
        try:
            data = _extract_json(raw)
            items = INSTRUCTIONS.validate_python(data.get("instructions", []))
            notes = [str(n) for n in data.get("notes", [])]
        except (ValueError, ValidationError, AttributeError) as exc:
            last = str(exc).splitlines()[0][:200]
            continue
        kept = []
        for ins in items:
            bad = [getattr(ins, a) for a in ("item", "from_item", "to_item")
                   if getattr(ins, a, None) is not None and getattr(ins, a) not in known]
            if bad:
                notes.append(f"{ins.quote or ins.kind} (unrecognised item {bad[0]!r})")
            else:
                kept.append(ins)
        return ParsedInstructions(instructions=kept, notes=notes, parser=client.name)
    raise MuseError(f"instruction parse invalid after retry: {last}")


def mock_reply(user_text: str) -> str:
    """What MockMuse answers for instruction prompts: the offline parse."""
    text = user_text.split("\n\n(Previous answer invalid", 1)[0]
    p = parse_offline(text)
    return json.dumps({"instructions": [i.model_dump() for i in p.instructions], "notes": p.notes})
