"""TextNormalizer — clean operator text token-by-token.

Per token, in order:

1. **Abbreviation expansion** — match the raw lowercased token (internal
   punctuation intact, so ``c/v`` and ``t/end`` match) against the
   :class:`AbbreviationStore`.
2. **Keep-as-is guards** — codes/IDs (contain a digit), very short tokens
   (< ``min_token_length``), and tokens the :class:`SpellEngine` already
   recognises as valid words (English *or* domain) are passed through.
   This is what stops real words like ``reset`` / ``tripping`` being mangled.
3. **Spelling correction** — for a genuine non-word, ask the engine for a
   suggestion and accept it **only if it lands in the domain dictionary**.
   ``beraing -> bearing`` (bearing is in the FMEA) is taken; ``esrl -> earl``
   (earl isn't) is rejected.
4. **Unknown** — anything left is recorded as an unknown token: a candidate
   for abbreviation/jargon mining (next pipeline stage).

Every change is recorded as a :class:`Correction` so the rewrite is auditable
and reversible. Nothing is silently mangled.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from orien_import_tool.textnorm.abbreviations import AbbreviationStore
from orien_import_tool.textnorm.dictionary import DomainDictionary
from orien_import_tool.textnorm.spell_engine import SpellEngine

_HAS_DIGIT = re.compile(r"\d")
_CORE_RE = re.compile(r"^([^\w]*)(.*?)([^\w]*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Correction:
    """One change the normaliser made, for audit / review."""

    original: str
    replacement: str
    method: str  # "abbreviation" | "spelling"
    confidence: float


@dataclass
class NormalizationResult:
    """Output of :meth:`TextNormalizer.normalize`."""

    original_text: str
    cleaned_text: str
    corrections: list[Correction] = field(default_factory=list)
    unknown_tokens: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.corrections)


class TextNormalizer:
    """Token-level spelling + abbreviation cleanup.

    ``min_token_length`` tokens shorter than this are never spell-corrected
    (short tokens collide too easily, and short non-words are usually codes
    worth flagging as unknown rather than guessing at).

    ``accept_only_domain_corrections`` (default True) is the safety gate that
    keeps correction precision high: a suggestion is only applied if it's a
    known domain term. Turn it off to accept any engine suggestion (noisier).
    """

    def __init__(
        self,
        dictionary: DomainDictionary,
        spell_engine: SpellEngine,
        abbreviations: AbbreviationStore | None = None,
        *,
        min_token_length: int = 4,
        accept_only_domain_corrections: bool = True,
        min_ratio: float = 0.80,
    ) -> None:
        self._dictionary = dictionary
        self._engine = spell_engine
        self._abbreviations = abbreviations
        self._min_token_length = min_token_length
        self._accept_only_domain = accept_only_domain_corrections
        self._min_ratio = min_ratio
        # Operator vocabulary is highly repetitive (the same terms recur
        # across thousands of events), and the spell engine's correction()
        # call is expensive. Memoise per raw token — the result is a pure
        # function of the token plus the (immutable) dictionary/engine.
        self._token_cache: dict[str, tuple[str, Correction | None, str | None]] = {}

    def normalize(self, text: str) -> NormalizationResult:
        corrections: list[Correction] = []
        unknown: list[str] = []
        out: list[str] = []

        for raw in text.split():
            replacement, correction, unknown_core = self._normalize_token(raw)
            out.append(replacement)
            if correction is not None:
                corrections.append(correction)
            if unknown_core is not None:
                unknown.append(unknown_core)

        return NormalizationResult(
            original_text=text,
            cleaned_text=" ".join(out),
            corrections=corrections,
            unknown_tokens=unknown,
        )

    # --- Internals -------------------------------------------------------------------

    def _normalize_token(
        self,
        raw: str,
    ) -> tuple[str, Correction | None, str | None]:
        """Return (replacement_text, correction_or_None, unknown_core_or_None)."""
        cached = self._token_cache.get(raw)
        if cached is not None:
            return cached
        result = self._compute_token(raw)
        self._token_cache[raw] = result
        return result

    def _compute_token(
        self,
        raw: str,
    ) -> tuple[str, Correction | None, str | None]:
        lowered = raw.casefold()

        # 1. Abbreviation expansion (full token, internal punctuation intact).
        if self._abbreviations is not None:
            expansion = self._abbreviations.expand(lowered)
            if expansion is not None:
                return expansion, Correction(raw, expansion, "abbreviation", 1.0), None

        prefix, core, suffix = _split_affixes(raw)
        core_lower = core.casefold()

        # 2. Keep-as-is guards.
        if (
            not core
            or _HAS_DIGIT.search(core)
            or len(core_lower) < self._min_token_length
            or self._engine.is_word(core_lower)
        ):
            return raw, None, None

        # 2b. Compound guard: a token that splits cleanly into two known words
        #     (pull+key, tail+end) is a concatenation, not a typo. Correcting
        #     "pullkey" to "pulley" would be wrong — leave it for mining /
        #     spaced-form normalisation. Generic across datasets.
        if self._is_compound(core_lower):
            return raw, None, core_lower

        # 3. Spelling correction. Accept only if: the suggestion is a domain
        #    term (precision gate) AND it's similar enough (the ratio floor
        #    rejects short codes that reach a domain word in <=2 edits but
        #    aren't really the same word — freq->free, etdt->end, fibre->fire).
        suggestion = self._engine.suggest(core_lower)
        if suggestion is not None and suggestion != core_lower:
            ratio = difflib.SequenceMatcher(None, core_lower, suggestion).ratio()
            domain_ok = not self._accept_only_domain or suggestion in self._dictionary
            if domain_ok and ratio >= self._min_ratio:
                replacement = f"{prefix}{suggestion}{suffix}"
                return replacement, Correction(raw, replacement, "spelling", ratio), None

        # 4. Unknown — leave untouched, flag for mining.
        return raw, None, core_lower

    def _is_compound(self, core: str) -> bool:
        """True if ``core`` splits into two known words (e.g. pull+key).

        Each part must be at least 3 characters so we don't treat a typo as a
        compound via a trivial 1-2 letter fragment.
        """
        for i in range(3, len(core) - 2):
            if self._engine.is_word(core[:i]) and self._engine.is_word(core[i:]):
                return True
        return False


def _split_affixes(token: str) -> tuple[str, str, str]:
    """Split a token into (leading_punct, core, trailing_punct)."""
    match = _CORE_RE.match(token)
    if match is None:  # pragma: no cover - regex always matches
        return "", token, ""
    return match.group(1), match.group(2), match.group(3)
