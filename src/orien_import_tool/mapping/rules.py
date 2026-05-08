"""Rule tables for mapping Orien Tactics vocabulary to ISO 14224 codes.

These were grown empirically against the conveyor fixture's 73-entry
mechanismAndCause vocabulary and 17-entry activityCode list. See
``data/mappings/`` for the SME-reviewable CSVs and
``data/iso14224/SCHEMA.md`` for the discussion of why each rule exists.

Patterns are first-match-wins for ``Y_TO_B3`` (most-specific phrases listed
ahead of broad catch-alls). ``VERB_TO_B2`` and ``Y_TO_B2`` are multi-tag —
every match contributes a B2 candidate and the proposer dedupes.
"""

from __future__ import annotations

import re

# --- X-side (failure-mode verb) -> B15 -----

VERB_TO_B15: list[tuple[str, str]] = [
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


# --- X-side verb -> B2 (multi-tag) -----
# Note: "separates" intentionally absent — it only appears in the compound
# "Breaks/Fracture/Separates" where Breakage already wins.

VERB_TO_B2: list[tuple[str, str]] = [
    ("wears", "Wear"),
    ("washes off", "Erosion"),
    ("corrodes", "Corrosion"),
    ("cracks", "Breakage"),
    ("fracture", "Breakage"),
    ("breaks", "Breakage"),
    # Severs covers both material removal and rupture.
    ("severs", "Wear"),
    ("severs", "Breakage"),
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


# --- Y-side (cause text) -> B2 multi-tag -----

Y_TO_B2: list[tuple[re.Pattern[str], str]] = [
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


# --- Y-side cause text -> B3 candidate list (most-likely-first) -----
# First matching pattern wins; specific phrases listed ahead of broad
# catch-alls.

Y_TO_B3: list[tuple[re.Pattern[str], list[str]]] = [
    # Mechanism-as-cause Y values that previously had no B3 — multi-candidate.
    (re.compile(r"breakdown.*insulation|electrical arcing"), ["1.4", "2.3", "2.1"]),
    (re.compile(r"\bvibration\b"), ["1.1", "1.5", "2.3"]),
    # Pure-environment temperature framings stay 3.4 only — match BEFORE the
    # generic "excessive temperature" pattern.
    (re.compile(r"in corrosive environment|exposure to.*temperature"), ["3.4"]),
    # Generic excessive / high temperature can be env or operating.
    (re.compile(r"excessive temperature|high temperature|temperature \(hot"), ["3.4", "2.1"]),
    # Thermal cycling and creep — environment OR design (not rated for service).
    (re.compile(r"thermal stress|creep"), ["3.4", "1.1"]),
    # Specific Orien phrases.
    (re.compile(r"excessive particle size"), ["2.1", "3.1", "1.1"]),
    (re.compile(r"insufficient fluid velocity"), ["1.1", "2.1", "2.3"]),
    (re.compile(r"excessive fluid velocity"), ["1.1", "2.1"]),
    (re.compile(r"\blow pressure\b"), ["1.1", "2.1", "2.3"]),
    (
        re.compile(r"mechanical overload|thermal overload|electrical overload|overcurrent"),
        ["2.1", "1.1"],
    ),
    (re.compile(r"cyclic loading"), ["1.1", "2.1"]),
    (re.compile(r"entrained air"), ["1.1", "2.1"]),
    (re.compile(r"crevice"), ["1.1", "1.5"]),
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
    # Generic design-error catch-all.
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


# --- Orien activityCode -> B5 (or B5 extension) -----

ACTIVITY_TO_B5: dict[str, tuple[str, str]] = {
    # (B5 activity name, justification)
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
    "Measure": ("Inspection", "B5:9 — measurement is a condition assessment"),
    "Oil Analysis": (
        "Inspection",
        "B5:9 — condition monitoring is a non-destructive inspection technique",
    ),
    "Operate": ("Other", "B5:12 — operating is not maintenance work"),
    "Repair": ("Repair", "direct"),
    "Replace": ("Replace", "direct"),
    "Statutory": ("Statutory", "B5 extension — regulatory mandate"),
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


def normalise(s: str) -> str:
    """Lowercase, strip non-alphanumeric, collapse whitespace."""
    return re.sub(r"[^a-z0-9 ]+", " ", s.casefold()).strip()
