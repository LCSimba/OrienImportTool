"""Interpret a spoken answer against a slot's valid options.

Speech-to-text output is noisy, so matching here is forgiving and works three
ways, in priority order:

1. **Ordinal pick** — "number two", "the third one", a bare "2". When the bot
   has just read a numbered list, this is the cleanest signal.
2. **Token / phrase fuzzy match** — overlap of normalised tokens plus a
   ``difflib`` ratio on the whole phrase, taken as the max over each option's
   label and its aliases. This catches "drive motor" against "Motor, drive
   end" and survives a dropped or mangled word.
3. **Yes / no** and **"don't know"** — small closed vocabularies the dialogue
   manager uses for confirmation and for the optional root-cause slot.

Everything reuses :func:`orien_import_tool.classification.preprocessor.normalise`
so the bot tokenises text the same way the rest of the platform does.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from orien_import_tool.classification.preprocessor import normalise, tokenise

# Confidence bands the dialogue manager keys off. A match at or above
# ``ACCEPT`` is read back for a single yes/no confirmation; between ``CONSIDER``
# and ``ACCEPT`` it is offered as one of a short disambiguation list; below
# ``CONSIDER`` it is treated as no match.
ACCEPT = 0.72
CONSIDER = 0.40


@dataclass(frozen=True, slots=True)
class Option:
    """One selectable value for a slot.

    ``value`` is what gets spoken back and stored; ``token`` is the canonical
    FMEA identifier when there is one (empty for free-text suggestions).
    ``aliases`` are extra spellings/phrasings that should also match.
    """

    value: str
    token: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """A scored option for an utterance, ``score`` in ``0..1``."""

    option: Option
    score: float

    @property
    def value(self) -> str:
        return self.option.value

    @property
    def token(self) -> str:
        return self.option.token


# NB: these are compared against ``normalise``d text, where ``normalise`` maps
# every non-alphanumeric run (including apostrophes) to a single space — so
# "don't" arrives here as "don t". Phrases are written in that normalised form.
_YES = frozenset(
    {
        "yes", "yeah", "yep", "yup", "ya", "correct", "right", "that s right",
        "that is right", "affirmative", "sure", "ok", "okay", "confirm",
        "confirmed", "true", "good", "exactly", "indeed",
    }
)
_NO = frozenset(
    {
        "no", "nope", "nah", "negative", "wrong", "incorrect", "not right",
        "that s wrong", "that is wrong", "cancel", "false",
    }
)
# Both apostrophe spellings appear: "don't" normalises to "don t", while a
# typed/recognised "dont" stays "dont" — cover both.
_DONT_KNOW = frozenset(
    {
        "don t know", "dont know", "do not know", "not sure", "unsure",
        "unknown", "no idea", "not known", "can t say", "cant say",
        "cannot say", "skip", "next", "none", "na", "not applicable",
        "pass", "no clue",
    }
)

_WORD_NUMBERS = {
    "one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3,
    "four": 4, "fourth": 4, "five": 5, "fifth": 5, "six": 6, "sixth": 6,
    "seven": 7, "seventh": 7, "eight": 8, "eighth": 8, "nine": 9, "ninth": 9,
    "ten": 10, "tenth": 10,
}


def parse_yes_no(utterance: str) -> bool | None:
    """Return ``True``/``False`` for affirmation/negation, else ``None``."""
    text = normalise(utterance)
    if not text:
        return None
    if text in _YES:
        return True
    if text in _NO:
        return False
    tokens = set(text.split())
    # A leading yes/no token wins even inside a longer phrase ("yes correct").
    if tokens & _NO:
        return False
    if tokens & _YES:
        return True
    return None


def is_dont_know(utterance: str) -> bool:
    """True when the speaker is declining to answer an optional slot."""
    text = normalise(utterance)
    if not text:
        return False
    if text in _DONT_KNOW:
        return True
    return any(
        phrase in text
        for phrase in ("don t know", "dont know", "do not know", "not sure", "no idea")
    )


def parse_ordinal(utterance: str, count: int) -> int | None:
    """Return a 1-based pick in ``1..count`` from "number two" / "3", else None."""
    if count <= 0:
        return None
    for token in tokenise(utterance, drop_stopwords=False):
        if token.isdigit():
            value = int(token)
            if 1 <= value <= count:
                return value
        elif token in _WORD_NUMBERS:
            value = _WORD_NUMBERS[token]
            if 1 <= value <= count:
                return value
    return None


def _phrase_score(utterance_norm: str, option_norm: str) -> float:
    """Blend token-overlap with a sequence ratio for one option string."""
    if not utterance_norm or not option_norm:
        return 0.0
    u_tokens = set(utterance_norm.split())
    o_tokens = set(option_norm.split())
    if not o_tokens:
        return 0.0

    # How much of the option's content the utterance covers, and vice-versa.
    overlap = len(u_tokens & o_tokens)
    coverage = overlap / len(o_tokens)
    precision = overlap / len(u_tokens) if u_tokens else 0.0
    ratio = SequenceMatcher(None, utterance_norm, option_norm).ratio()

    # Coverage dominates (did they name the option?), tempered by how much of
    # what they said was on-topic and by overall string similarity.
    score = 0.6 * coverage + 0.2 * precision + 0.2 * ratio
    # An exact phrase match is as certain as an ordinal pick — commit it
    # without a confirmation turn. Full containment is strong but still worth
    # a quick read-back, so it lands just inside the accept band.
    if option_norm == utterance_norm:
        return 1.0
    if o_tokens <= u_tokens:
        score = max(score, 0.85)
    return min(score, 1.0)


def score_option(utterance: str, option: Option) -> float:
    """Best phrase score over the option's value and any aliases."""
    u_norm = normalise(utterance)
    candidates = [option.value, *option.aliases]
    return max(_phrase_score(u_norm, normalise(c)) for c in candidates)


def match_options(
    utterance: str,
    options: list[Option],
    *,
    limit: int = 3,
) -> list[MatchCandidate]:
    """Rank ``options`` for ``utterance``.

    An ordinal pick ("number two") short-circuits to that option at full
    confidence. Otherwise every option is fuzzy-scored and the best ``limit``
    above :data:`CONSIDER` are returned, highest first.
    """
    if not options:
        return []

    pick = parse_ordinal(utterance, len(options))
    if pick is not None:
        return [MatchCandidate(option=options[pick - 1], score=1.0)]

    scored = [MatchCandidate(option=o, score=score_option(utterance, o)) for o in options]
    scored.sort(key=lambda c: c.score, reverse=True)
    return [c for c in scored if c.score >= CONSIDER][:limit]
