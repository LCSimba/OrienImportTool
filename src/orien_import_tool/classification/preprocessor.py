"""Text preprocessing for downtime classification.

The classifier compares tokens in the downtime text to tokens in the seed
vocabulary. Both sides go through the same ``normalise`` / ``tokenise`` so the
comparisons are apples-to-apples.

The stopword list is deliberately tiny — equipment vocabulary contains terms
like ``of`` (e.g. "Loss of containment") and ``in`` (e.g. "Breakdown in
insulation") that we cannot afford to drop. We only filter universally
content-free fillers.
"""

from __future__ import annotations

import re

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "was",
        "be",
        "been",
        "being",
        "to",
        "and",
        "or",
        "for",
        "with",
        "without",
    }
)


_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    """Lowercase, replace non-alphanumeric runs with single spaces, strip."""
    return _NORMALISE_RE.sub(" ", text.casefold()).strip()


def tokenise(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Tokenise normalised text into content tokens.

    ``drop_stopwords=False`` is useful when matching against a seed term
    that is itself a stopword-containing phrase ("Breakdown in insulation");
    the caller can compare exact phrases.
    """
    tokens = normalise(text).split()
    if drop_stopwords:
        tokens = [t for t in tokens if t not in _STOPWORDS]
    return tokens
