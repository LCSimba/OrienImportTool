"""In-memory :class:`AliasStore`.

Persistence is deferred to the Postgres chunk; the API here is the contract
that the eventual repository will satisfy.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator

from orien_import_tool.aliases.models import Alias
from orien_import_tool.classification.preprocessor import normalise


class AliasStore:
    """Holds aliases keyed by normalised alias text.

    Multiple aliases may share an ``alias_text`` (e.g. a global rule alias and
    an SME override). All matching aliases contribute their canonical tokens
    to the expansion.
    """

    def __init__(self) -> None:
        self._by_text: dict[str, list[Alias]] = defaultdict(list)

    # --- Mutation ----------------------------------------------------------------

    def add(self, alias: Alias) -> None:
        normalised = normalise(alias.alias_text)
        if not normalised:
            return
        # Avoid exact duplicates (same text + proposer + canonical_tokens + scope).
        key = (
            tuple(sorted(alias.canonical_tokens)),
            alias.proposer,
            alias.scope_equipment_token,
        )
        for existing in self._by_text[normalised]:
            existing_key = (
                tuple(sorted(existing.canonical_tokens)),
                existing.proposer,
                existing.scope_equipment_token,
            )
            if existing_key == key:
                return
        self._by_text[normalised].append(alias)

    def add_many(self, aliases: Iterable[Alias]) -> None:
        for alias in aliases:
            self.add(alias)

    # --- Lookup ------------------------------------------------------------------

    def get(self, alias_text: str) -> list[Alias]:
        return list(self._by_text.get(normalise(alias_text), []))

    def __contains__(self, alias_text: object) -> bool:
        if not isinstance(alias_text, str):
            return False
        return normalise(alias_text) in self._by_text

    def __iter__(self) -> Iterator[Alias]:
        for aliases in self._by_text.values():
            yield from aliases

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_text.values())

    # --- Token expansion (the integration point with the classifier) -------------

    def expand_token(
        self,
        token: str,
        *,
        equipment_token: str | None = None,
    ) -> set[str]:
        """Return the set of canonical tokens that ``token`` expands to.

        Aliases whose ``scope_equipment_token`` is set must match the supplied
        ``equipment_token`` (or be global) to contribute.
        """
        out: set[str] = set()
        for alias in self._by_text.get(normalise(token), ()):
            if (
                alias.scope_equipment_token is None
                or alias.scope_equipment_token == equipment_token
            ):
                out.update(alias.canonical_tokens)
        return out

    def expand_tokens(
        self,
        tokens: Iterable[str],
        *,
        equipment_token: str | None = None,
    ) -> set[str]:
        """Expand each token via :meth:`expand_token`, return the union."""
        out: set[str] = set()
        for token in tokens:
            out.update(self.expand_token(token, equipment_token=equipment_token))
        return out
