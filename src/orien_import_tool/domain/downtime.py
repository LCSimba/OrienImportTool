"""Domain model for downtime events and their classifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DowntimeEvent:
    """One operator-entered downtime record.

    ``external_id`` is the natural key from the source system (CMMS,
    historian). ``asset_ref`` is the operator's free-text reference to a
    machine — typically a tag like ``4FC025`` or a description; the
    classifier resolves it to a canonical Component when possible.

    ``start_ts`` is optional — many CMMS exports carry only descriptive
    rows without timestamps, especially aggregated category tables. The
    classifier doesn't use timestamps for matching, so an undated record
    is still useful.

    ``text`` is the full composed record (free-text *and* validated/coded
    columns) — the classifier matches against it because the coded
    descriptions are useful signal. ``free_text`` is the operator-typed
    subset only (the CMMS TextLine fields); spelling/abbreviation cleanup
    and mining run against *this*, never the validated columns, which carry
    their own descriptions and must not be "corrected". It defaults to ``""``;
    consumers that want the noisy text fall back to ``free_text or text``.

    ``coded_context`` holds the row's validated/coded labels (category,
    component description, table description) as distinct strings. These are
    *not* matched or corrected, but they're high-value disambiguation context
    when asking an LLM what an unknown token means — an ``espk`` seen on rows
    labelled "CONTROL & INSTR" reads very differently from one on "BELT".
    """

    external_id: str
    asset_ref: str
    text: str
    free_text: str = ""
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    duration_s: float | None = None
    source_system: str = ""
    coded_context: tuple[str, ...] = ()
    text_line3: str = ""  # the richest operator narrative line (CMMS TextLine3)


@dataclass(frozen=True, slots=True)
class ExtractedEntities:
    """Open extraction from one event's cleaned operator text.

    Produced *before* any FMEA matching: ``components`` and ``failure_modes``
    are what the operator text actually mentions (failure modes tagged
    deterministically against the generic ISO/alias vocabulary; components
    pulled by an LLM). Linking these to the equipment FMEA is a later stage.
    """

    event_external_id: str
    cleaned_text: str
    components: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComponentMatch:
    """A scored Component candidate for a downtime event."""

    component_token: str
    component_description: str
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FailureModeCandidate:
    """A scored FailureMode candidate for a downtime event."""

    failure_mode_token: str
    component_token: str
    score: float
    matched_terms: tuple[str, ...]
    rationale: str = ""


@dataclass
class DowntimeClassification:
    """Classifier output for one :class:`DowntimeEvent`.

    ``component_match`` is the best Component candidate (or ``None`` if no
    match). ``failure_mode_candidates`` is ordered most-likely first and may
    be empty. ``proposer`` distinguishes rule-based vs LLM-assisted output.
    """

    event_external_id: str
    component_match: ComponentMatch | None
    failure_mode_candidates: list[FailureModeCandidate] = field(default_factory=list)
    proposer: str = "alias-rule"
    notes: str = ""

    @property
    def best_failure_mode(self) -> FailureModeCandidate | None:
        return self.failure_mode_candidates[0] if self.failure_mode_candidates else None

    @property
    def needs_review(self) -> bool:
        """A classification needs review when the top candidate is weak or there is none."""
        if not self.failure_mode_candidates:
            return True
        top = self.failure_mode_candidates[0]
        return top.score < 0.5
