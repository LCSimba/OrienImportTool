# ruff: noqa: E501
"""Generate the proposed Orien -> ISO 14224 mapping CSVs.

Exploratory script — the rule logic here is the seed for the codified
``orien_import_tool.mapping`` module that lands in Chunk 3. Re-run any time
the rules or fixtures change:

    python scripts/generate_orien_iso_mapping.py

Outputs ``data/mappings/orien_mechanism_cause_to_iso.csv`` and
``data/mappings/orien_activity_code_to_iso.csv``.

E501 is ignored for this file because the rule patterns are clearer kept on
single lines than wrapped.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from orien_import_tool.iso14224 import load_all  # noqa: E402

ref = load_all(ROOT / "data" / "iso14224")
b2_by_subname = {m.sub_name: m for m in ref.failure_mechanisms.values()}
b5_by_activity = {a.activity: a for a in ref.maintenance_activities.values()}


# --- X-side verb -> B15 -----

VERB_TO_B15 = [
    ("breaks", "Cracked/fractured/broken"),
    ("fracture", "Cracked/fractured/broken"),
    ("cracks", "Cracked/fractured/broken"),
    ("severs", "Cracked/fractured/broken"),
    ("arcs", "Electrical short"),
    ("short circuits", "Electrical short"),
    ("blocks", "Blocked/plugged/restricted"),
    ("corrodes", "Corroded"),
    ("degrades", "Worn"),
    ("wears", "Worn"),
    ("distorts", "Deformed"),
    ("drifts", "Out of adjustment/calibration drift"),
    ("expires", "Miscellaneous"),
    ("immobilised", "Seized/jammed/stuck"),
    ("binds", "Seized/jammed/stuck"),
    ("jams", "Seized/jammed/stuck"),
    ("loses preload", "Loose/disconnected"),
    ("separates", "Loose/disconnected"),
    ("open circuit", "Open circuit"),
    ("overheats", "Overheating"),
    ("melts", "Overheating"),
    ("burns", "Overheating"),
    ("thermally overloads", "Overheating"),
    ("washes off", "Eroded"),
]


# --- X-side verb -> B2 (note: "separates" intentionally absent) -----

VERB_TO_B2 = [
    ("wears", "Wear"),
    ("washes off", "Erosion"),
    ("corrodes", "Corrosion"),
    ("cracks", "Breakage"),
    ("fracture", "Breakage"),
    ("breaks", "Breakage"),
    ("severs", "Wear"),
    ("overheats", "Overheating"),
    ("melts", "Overheating"),
    ("burns", "Overheating"),
    ("thermally overloads", "Overheating"),
    ("open circuit", "Open circuit"),
    ("short circuits", "Short circuiting"),
    ("arcs", "Short circuiting"),
    ("loses preload", "Looseness"),
    ("distorts", "Deformation"),
    ("binds", "Sticking"),
    ("jams", "Sticking"),
    ("immobilised", "Sticking"),
    ("blocks", "Blockage/plugged"),
    ("drifts", "Out of adjustment"),
    ("degrades", "Wear"),
]


# --- Y-side multi-tag B2 -----

Y_TO_B2 = [
    (re.compile(r"\bvibration\b"), "Vibration"),
    (re.compile(r"fatigue|cyclic"), "Fatigue"),
    (re.compile(r"creep"), "Deformation"),
    (re.compile(r"contamination|contaminat"), "Contamination"),
    (re.compile(r"crevice|dissimilar metals"), "Corrosion"),
    (
        re.compile(r"chemical attack|chemical reaction|bio.?organism|corrosive|atmosphere"),
        "Corrosion",
    ),
    (re.compile(r"relative movement|metal to metal|rubbing|abrasion|fretting"), "Wear"),
    (re.compile(r"lubricant|lubrication"), "Wear"),
    (re.compile(r"\belectrical arc"), "Short circuiting"),
    (re.compile(r"stray current"), "Corrosion"),
    (re.compile(r"breakdown.*insulation"), "Short circuiting"),
    (re.compile(r"entrained air"), "Cavitation"),
    (re.compile(r"\blow pressure"), "Cavitation"),
    (re.compile(r"thermal stress"), "Fatigue"),
    (re.compile(r"excessive fluid velocity"), "Erosion"),
    (
        re.compile(r"high temperature|excessive temperature|thermal overload|overheating"),
        "Overheating",
    ),
    (re.compile(r"electrical overload|overcurrent"), "Short circuiting"),
    (re.compile(r"impact|shock"), "Breakage"),
    (re.compile(r"\bage\b|wear and tear|\buse\b"), "Wear"),
]


# --- Y-side B3 — multi-candidate where genuinely ambiguous -----
#
# Each entry returns one or more B3 sub_codes ordered most-likely first. The
# SME review picks from the shortlist. Specific patterns first, broad patterns
# last; first-match-wins.

Y_TO_B3: list[tuple[re.Pattern[str], list[str]]] = [
    # Specific Orien phrases first (more specific than the generic patterns below).
    (
        re.compile(r"excessive particle size"),
        ["2.1", "3.1", "1.1"],
    ),  # operating > contamination > design
    (re.compile(r"insufficient fluid velocity|excessive fluid velocity"), ["1.1", "2.1"]),
    (re.compile(r"\blow pressure\b"), ["1.1", "2.1", "2.3"]),
    (
        re.compile(r"mechanical overload|thermal overload|electrical overload|overcurrent"),
        ["2.1", "1.1"],
    ),
    (re.compile(r"cyclic loading"), ["1.1", "2.1"]),
    (re.compile(r"entrained air"), ["1.1", "2.1"]),
    (re.compile(r"crevice"), ["1.1"]),
    (re.compile(r"dissimilar metals"), ["1.1", "1.5"]),
    (re.compile(r"off.?center|uneven loading"), ["1.5", "2.1"]),
    (re.compile(r"poor electrical connection"), ["1.5", "2.3"]),
    (re.compile(r"poor electrical insulation"), ["1.4", "2.3"]),
    (re.compile(r"breakdown of lubrication"), ["2.3", "1.2"]),
    (re.compile(r"lack of lubrication|insufficient lub"), ["2.3"]),
    (re.compile(r"metal to metal contact|relative movement|rubbing"), ["2.3"]),
    (re.compile(r"abrasion"), ["3.1"]),
    # Manufacturing / Material / Installation
    (re.compile(r"manufacturing.*defect|defects introduced"), ["1.3"]),
    (re.compile(r"material defect"), ["1.4"]),
    (re.compile(r"installation|misalign"), ["1.5"]),
    # Generic design-error catch-all (after specific phrases above).
    (re.compile(r"design.*error|specification|capacity|undersized|oversized|inadequate"), ["1.1"]),
    # Operating
    (re.compile(r"operating error|wrong sequence|exceeding limits"), ["2.1"]),
    (re.compile(r"wrong medium|wrong fluid"), ["2.2"]),
    (re.compile(r"maintenance.*error"), ["2.3"]),
    (re.compile(r"test error"), ["2.4"]),
    # External
    (re.compile(r"contamination"), ["3.1"]),
    (re.compile(r"impact|shock"), ["3.3"]),
    (
        re.compile(
            r"environment|atmosphere|temperature|humidity|radiation|chemical|"
            r"corrosive|bio.?organism|stray current|liquid metal|thermal stress|creep"
        ),
        ["3.4"],
    ),
    (re.compile(r"natural|earthquake|flood|lightning"), ["3.5"]),
    # Other
    (re.compile(r"\bage\b|wear and tear|\buse\b"), ["4.3"]),
]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.casefold()).strip()


def map_b15(x: str) -> str | None:
    nx = norm(x)
    tokens = re.split(r"[\s/]+", nx)
    for token in tokens:
        for verb, target in VERB_TO_B15:
            if verb == token:
                return target
    for verb, target in VERB_TO_B15:
        if " " in verb and verb in nx:
            return target
    return None


def map_b2_multi(x: str, y: str) -> list[str]:
    nx, ny = norm(x), norm(y)
    found: list[str] = []
    tokens_x = re.split(r"[\s/]+", nx)
    for verb, target in VERB_TO_B2:
        if (verb in tokens_x or (" " in verb and verb in nx)) and target not in found:
            found.append(target)
    for pattern, target in Y_TO_B2:
        if pattern.search(ny) and target not in found:
            found.append(target)
    return found


def map_b3_candidates(y: str) -> list[str]:
    """First matching pattern wins; it returns one or more candidate sub_codes."""
    ny = norm(y)
    for pattern, candidates in Y_TO_B3:
        if pattern.search(ny):
            return list(candidates)
    return []


# --- Pull vocabularies from the conveyor fixture -----

FIXTURE = (
    ROOT
    / "tests/fixtures/orien/2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"
)
wb = openpyxl.load_workbook(FIXTURE, data_only=True)
dropdown_rows = list(wb["r8DropdownValues"].iter_rows(values_only=True))
mech_cause_vocab = [v for v in dropdown_rows[6] if v]
activity_vocab = [v for v in dropdown_rows[13] if v]


# --- Build mechanism+cause CSV -----

mc_rows = []
for value in mech_cause_vocab:
    parts = re.split(r"\s+due to\s+", value, flags=re.IGNORECASE, maxsplit=1)
    x = parts[0]
    y = parts[1] if len(parts) > 1 else ""

    b15_code = map_b15(x)
    b15_obj = ref.failure_modes.get(b15_code) if b15_code else None
    b2_subnames = map_b2_multi(x, y)
    b3_subcodes = map_b3_candidates(y)
    b3_subnames = [ref.failure_causes[c].sub_name for c in b3_subcodes if c in ref.failure_causes]

    has_b15 = bool(b15_code)
    has_b2 = bool(b2_subnames)
    has_b3 = bool(b3_subcodes)
    b3_unique = len(b3_subcodes) == 1
    if has_b15 and has_b2 and b3_unique:
        confidence = "high"
    elif has_b15 and has_b2 and has_b3:
        confidence = "medium"  # multi-candidate B3 needs SME pick
    elif has_b15 and has_b2:
        confidence = "low"  # no B3 at all
    else:
        confidence = "none"

    mc_rows.append(
        {
            "orien_mechanism_and_cause": value,
            "x": x,
            "y": y,
            "b15_code": b15_code or "",
            "b15_description": b15_obj.description if b15_obj else "",
            "b2_sub_codes": ",".join(
                b2_by_subname[n].sub_code for n in b2_subnames if n in b2_by_subname
            ),
            "b2_sub_names": ",".join(b2_subnames),
            "b3_sub_codes": ",".join(b3_subcodes),
            "b3_sub_names": ",".join(b3_subnames),
            "b3_candidate_count": len(b3_subcodes),
            "confidence": confidence,
            "proposer": "rule",
            "needs_review": "" if confidence == "high" else "Y",
        }
    )

mc_path = ROOT / "data/mappings/orien_mechanism_cause_to_iso.csv"
with mc_path.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(mc_rows[0]))
    writer.writeheader()
    writer.writerows(mc_rows)


# --- Activity-code CSV -----

ACTIVITY_MAP = {
    "Adjust": ("Adjust", "direct"),
    "Calibrate": ("Adjust", 'B5:4 examples include "calibrate"'),
    "Check": ("Check", "direct"),
    "Clean": ("Service", 'B5:7 examples include "Cleaning"'),
    "Fluid Analysis": (
        "Inspection",
        "B5:9 — condition monitoring is a non-destructive inspection technique",
    ),
    "Inspection": ("Inspection", "direct"),
    "Lube": ("Refit", 'B5:5 examples include "lube, oil change"'),
    "Measure": (
        "Inspection",
        "B5:9 — measurement is a condition assessment (thickness / clearance / runout)",
    ),
    "Oil Analysis": (
        "Inspection",
        "B5:9 — condition monitoring is a non-destructive inspection technique",
    ),
    "Operate": ("Other", "B5:12 — operating is not maintenance work"),
    "Repair": ("Repair", "direct"),
    "Replace": ("Replace", "direct"),
    "Statutory": (
        "Statutory",
        "B5 extension — regulatory mandate; underlying work is typically Inspection or Test",
    ),
    "Test": ("Test", "direct"),
    "Thermography": (
        "Inspection",
        "B5:9 — condition monitoring is a non-destructive inspection technique",
    ),
    "Ultrasonic Testing": (
        "Inspection",
        "B5:9 — condition monitoring is a non-destructive inspection technique",
    ),
    "Vibration Analysis": (
        "Inspection",
        "B5:9 — condition monitoring is a non-destructive inspection technique",
    ),
}

ac_rows = []
for code in activity_vocab:
    target, why = ACTIVITY_MAP[code]
    b5 = b5_by_activity[target]
    ac_rows.append(
        {
            "orien_activity_code": code,
            "b5_code_number": b5.code_number,
            "b5_activity": b5.activity,
            "b5_use": b5.use,
            "justification": why,
            "proposer": "rule",
            # Direct name match (Adjust->Adjust, Statutory->Statutory) is high
            # confidence; matches via B5 description/examples are medium.
            "confidence": "high" if code == target else "medium",
        }
    )

ac_path = ROOT / "data/mappings/orien_activity_code_to_iso.csv"
with ac_path.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(ac_rows[0]))
    writer.writeheader()
    writer.writerows(ac_rows)


# --- Coverage report -----


def cov(rows: list[dict], pred) -> str:
    n = sum(1 for r in rows if pred(r))
    return f"{n:3d}/{len(rows)} ({n / len(rows):.0%})"


print(f"Wrote {mc_path}  ({len(mc_rows)} rows)")
print(f"  B15:                       {cov(mc_rows, lambda r: r['b15_code'])}")
print(f"  B2:                        {cov(mc_rows, lambda r: r['b2_sub_codes'])}")
print(f"  B3 (any candidate):        {cov(mc_rows, lambda r: r['b3_sub_codes'])}")
print(f"  B3 (single unambiguous):   {cov(mc_rows, lambda r: r['b3_candidate_count'] == 1)}")
print(f"  high confidence:           {cov(mc_rows, lambda r: r['confidence'] == 'high')}")
print(f"  medium (multi-cand B3):    {cov(mc_rows, lambda r: r['confidence'] == 'medium')}")
print(f"  low (no B3):               {cov(mc_rows, lambda r: r['confidence'] == 'low')}")
print()
print(f"Wrote {ac_path}  ({len(ac_rows)} rows)")
