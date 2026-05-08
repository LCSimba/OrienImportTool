"""Rule-based mapping proposer — Orien canonical model -> ISO 14224 codes.

Walks an :class:`Equipment` tree and emits :class:`Iso14224Mapping` rows. For
each :class:`FailureMode` it produces up to one MODE (B15) mapping and any
number of MECHANISM (B2) and CAUSE (B3) candidates. For each :class:`Activity`
it produces exactly one MAINTENANCE_ACTIVITY (B5 or B5 extension) mapping.

Confidence values are heuristic bands:

* ``1.0`` — direct ISO name match (Orien activityCode == B5 activity name).
* ``0.9`` — single-candidate rule match.
* ``0.7`` — primary multi-candidate (priority 0).
* ``0.5`` — first alternate (priority 1).
* ``0.3`` — second alternate or weaker (priority 2+).
"""

from __future__ import annotations

import re

from orien_import_tool.domain.fmea import Activity, Equipment, FailureMode
from orien_import_tool.iso14224 import Iso14224ReferenceSet
from orien_import_tool.mapping.models import (
    Iso14224Mapping,
    MappingDimension,
    MappingResult,
    Proposer,
)
from orien_import_tool.mapping.rules import (
    ACTIVITY_TO_B5,
    VERB_TO_B2,
    VERB_TO_B15,
    Y_TO_B2,
    Y_TO_B3,
    normalise,
)


class RuleProposer:
    """Stateless proposer driven by ``rules.py``.

    The reference set is held to validate ISO codes exist; the proposer never
    invents codes.
    """

    def __init__(self, ref: Iso14224ReferenceSet) -> None:
        self._ref = ref
        self._b2_subname_to_subcode = {
            m.sub_name: m.sub_code for m in ref.failure_mechanisms.values()
        }

    # --- Public API ---------------------------------------------------------------

    def propose_for_failure_mode(self, fm: FailureMode) -> list[Iso14224Mapping]:
        """Return MODE / MECHANISM / CAUSE candidates for one FailureMode."""
        x, y = _split_mechanism_and_cause(fm.mechanism_and_cause)
        out: list[Iso14224Mapping] = []
        out.extend(self._propose_mode(fm, x))
        out.extend(self._propose_mechanism(fm, x, y))
        out.extend(self._propose_cause(fm, y))
        return out

    def propose_for_activity(self, activity: Activity) -> list[Iso14224Mapping]:
        """Return one MAINTENANCE_ACTIVITY mapping for the activity_code.

        When ``activity_code`` is blank (as it is throughout the conveyor
        fixture), no mapping is emitted. ``activity_type`` is intentionally not
        a fallback — it carries Predictive / Corrective / Preventative which is
        a different axis (B5's ``use`` column, not the activity itself).
        """
        code = activity.activity_code
        if not code or code not in ACTIVITY_TO_B5:
            return []
        b5_name, justification = ACTIVITY_TO_B5[code]
        b5 = next(
            (a for a in self._ref.maintenance_activities.values() if a.activity == b5_name),
            None,
        )
        if b5 is None:
            return []
        confidence = 1.0 if code == b5_name else 0.7
        return [
            Iso14224Mapping(
                source_entity_type="Activity",
                source_entity_id=activity.token,
                dimension=MappingDimension.MAINTENANCE_ACTIVITY,
                iso_code=str(b5.code_number),
                proposer=Proposer.RULE,
                confidence=confidence,
                rationale=justification,
                priority=0,
            )
        ]

    # --- Internals ----------------------------------------------------------------

    def _propose_mode(self, fm: FailureMode, x: str) -> list[Iso14224Mapping]:
        if not x:
            return []
        b15_code = _match_b15(x)
        if not b15_code or b15_code not in self._ref.failure_modes:
            return []
        return [
            Iso14224Mapping(
                source_entity_type="FailureMode",
                source_entity_id=fm.token,
                dimension=MappingDimension.MODE,
                iso_code=b15_code,
                proposer=Proposer.RULE,
                confidence=0.9,
                rationale=f"Verb match on {x!r}",
                priority=0,
            )
        ]

    def _propose_mechanism(self, fm: FailureMode, x: str, y: str) -> list[Iso14224Mapping]:
        sub_names = _match_b2_multi(x, y)
        out: list[Iso14224Mapping] = []
        for i, name in enumerate(sub_names):
            sub_code = self._b2_subname_to_subcode.get(name)
            if not sub_code:
                continue
            confidence = 0.9 if len(sub_names) == 1 else (0.7 if i == 0 else 0.5)
            out.append(
                Iso14224Mapping(
                    source_entity_type="FailureMode",
                    source_entity_id=fm.token,
                    dimension=MappingDimension.MECHANISM,
                    iso_code=sub_code,
                    proposer=Proposer.RULE,
                    confidence=confidence,
                    rationale=f"Mechanism candidate {name!r} from x/y match",
                    priority=i,
                )
            )
        return out

    def _propose_cause(self, fm: FailureMode, y: str) -> list[Iso14224Mapping]:
        sub_codes = _match_b3_candidates(y)
        out: list[Iso14224Mapping] = []
        for i, sub_code in enumerate(sub_codes):
            if sub_code not in self._ref.failure_causes:
                continue
            if len(sub_codes) == 1:
                confidence = 0.9
            elif i == 0:
                confidence = 0.7
            elif i == 1:
                confidence = 0.5
            else:
                confidence = 0.3
            out.append(
                Iso14224Mapping(
                    source_entity_type="FailureMode",
                    source_entity_id=fm.token,
                    dimension=MappingDimension.CAUSE,
                    iso_code=sub_code,
                    proposer=Proposer.RULE,
                    confidence=confidence,
                    rationale=f"Cause candidate from {y!r}",
                    priority=i,
                )
            )
        return out


def propose_mappings(equipment: Equipment, ref: Iso14224ReferenceSet) -> MappingResult:
    """Walk the FMEA tree and produce all rule-based mappings for it."""
    proposer = RuleProposer(ref)
    result = MappingResult(equipment_token=equipment.token)
    for component in equipment.components:
        for function in component.functions:
            for failure in function.failures:
                for fm in failure.failure_modes:
                    result.mappings.extend(proposer.propose_for_failure_mode(fm))
                    for activity in fm.activities:
                        result.mappings.extend(proposer.propose_for_activity(activity))
    return result


# --- Pattern helpers (mirror scripts/generate_orien_iso_mapping.py) -----------------


def _split_mechanism_and_cause(text: str) -> tuple[str, str]:
    """Split an Orien ``mechanismAndCause`` string at " due to " (case-insensitive)."""
    parts = re.split(r"\s+due to\s+", text, flags=re.IGNORECASE, maxsplit=1)
    x = parts[0]
    y = parts[1] if len(parts) > 1 else ""
    return x, y


def _match_b15(x: str) -> str | None:
    nx = normalise(x)
    tokens = re.split(r"[\s/]+", nx)
    for token in tokens:
        for verb, target in VERB_TO_B15:
            if verb == token:
                return target
    for verb, target in VERB_TO_B15:
        if " " in verb and verb in nx:
            return target
    return None


def _match_b2_multi(x: str, y: str) -> list[str]:
    nx, ny = normalise(x), normalise(y)
    found: list[str] = []
    tokens_x = re.split(r"[\s/]+", nx)
    for verb, target in VERB_TO_B2:
        if (verb in tokens_x or (" " in verb and verb in nx)) and target not in found:
            found.append(target)
    for pattern, target in Y_TO_B2:
        if pattern.search(ny) and target not in found:
            found.append(target)
    return found


def _match_b3_candidates(y: str) -> list[str]:
    ny = normalise(y)
    for pattern, candidates in Y_TO_B3:
        if pattern.search(ny):
            return list(candidates)
    return []
