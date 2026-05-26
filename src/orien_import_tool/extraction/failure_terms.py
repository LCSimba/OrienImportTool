"""Deterministic failure-mode tagging from a generic failure vocabulary.

The hybrid extractor tags failure modes *without* the LLM: a token in the
cleaned (and alias-expanded) operator text counts as a failure-mode mention if
it lands in a generic vocabulary built from

* a curated set of canonical + operator-side failure terms (broken, fracture,
  blocked, tripped, seized, worn, ...) — domain-general, transfers across data,
* the ISO 14224 B.15 failure-mode descriptions.

Alias expansion at tag time bridges operator words to the canonical terms that
already live in this set (broken -> fracture). The vocabulary is intentionally
*not* drawn from the alias store, which also maps to component tokens (belt,
chute) and would tag components as failures.

This is the deliberately conservative, inspectable half of the pipeline —
components, which need real language understanding, go to the LLM.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orien_import_tool.iso14224 import Iso14224ReferenceSet

# Canonical / operator-side failure terms. Lowercase, single tokens. Kept
# domain-general (no conveyor specifics) so it transfers across datasets.
_GENERIC_FAILURE_TERMS: frozenset[str] = frozenset(
    {
        # canonical (alias targets / ISO-aligned)
        "failure",
        "failed",
        "fault",
        "faulty",
        "fracture",
        "fractured",
        "breakage",
        "broken",
        "breaks",
        "crack",
        "cracked",
        "cracking",
        "blockage",
        "blocked",
        "plugged",
        "restricted",
        "stoppage",
        "stopped",
        "trip",
        "tripped",
        "shutdown",
        "looseness",
        "loose",
        "disconnected",
        "vibration",
        "corrosion",
        "corroded",
        "erosion",
        "eroded",
        "wear",
        "worn",
        "fatigue",
        "deformation",
        "deformed",
        "distorted",
        "bent",
        "leak",
        "leaking",
        "leakage",
        "seized",
        "jammed",
        "stuck",
        "binding",
        "overheated",
        "overheating",
        "burnt",
        "burned",
        "melted",
        "snapped",
        "severed",
        "rubbing",
        "fretting",
        "abrasion",
        "cavitation",
        "spillage",
        "misalignment",
        "misaligned",
        "slipping",
        "slip",
        "overload",
        "overloaded",
        "noisy",
        "damaged",
        "damage",
        "collapse",
        "collapsing",
        # broader mechanical / belt + remaining alias-miner verbs
        "arcs",
        "arcing",
        "separates",
        "separation",
        "corrodes",
        "degrades",
        "degraded",
        "distorts",
        "drifts",
        "drift",
        "binds",
        "melts",
        "overheats",
        "burns",
        "severs",
        "sticking",
        "sticks",
        "stop",
        "ruptured",
        "rupture",
        "split",
        "torn",
        "tear",
        "frayed",
        "perished",
        "chafed",
        "ripped",
        "sheared",
        "loosened",
        "blockages",
    }
)

# B.15 words that are not themselves failure modes (signal/output plumbing).
_NON_FAILURE_WORDS: frozenset[str] = frozenset(
    {"output", "signal", "indication", "alarm", "control", "high", "low", "no", "minor", "major"}
)

_WORD_RE = re.compile(r"[^a-z]+")


def build_failure_vocabulary(ref: Iso14224ReferenceSet | None = None) -> frozenset[str]:
    """Assemble the generic failure-term set: curated terms + ISO B.15 words.

    Deliberately does *not* pull from the alias store — those map operator
    words to *component* tokens too (belt, chute, detector), which would
    pollute the failure vocabulary and tag components as failures. Alias
    *expansion* still bridges operator failure words to canonical terms at tag
    time; the canonical failure terms it produces already live in this set.
    """
    vocab: set[str] = set(_GENERIC_FAILURE_TERMS)
    if ref is not None:
        for description in ref.failure_modes:  # keys are the B.15 descriptions
            for word in _WORD_RE.split(description.casefold()):
                if len(word) >= 4 and word not in _NON_FAILURE_WORDS:
                    vocab.add(word)
    return frozenset(vocab)


def tag_failure_modes(tokens: Iterable[str], vocabulary: frozenset[str]) -> tuple[str, ...]:
    """Return the failure-mode terms present in ``tokens`` (sorted, de-duped)."""
    return tuple(sorted({t.casefold() for t in tokens} & vocabulary))
