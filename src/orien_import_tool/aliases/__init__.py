"""Alias / Term store — operator vocabulary -> canonical FMEA tokens.

The store holds one or more :class:`Alias` rows per operator term, each
pointing at a tuple of canonical tokens that already appear in the FMEA seed
index. The classifier consults the store at scoring time so an event saying
``TRIPPED`` can match a FailureMode whose text says ``stoppage``.

Aliases come from three sources, distinguished by ``proposer``:

* ``rule`` — seeded deterministically (e.g. each FMEA verb maps to itself).
* ``llm`` — proposed by :class:`LLMAliasMiner` from unmatched events.
* ``sme`` — confirmed or hand-entered by an SME.
"""

from orien_import_tool.aliases.miner import (
    AliasProposal,
    AliasProposalBatch,
    LLMAliasMiner,
)
from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.aliases.seed import build_initial_alias_store
from orien_import_tool.aliases.store import AliasStore

__all__ = [
    "Alias",
    "AliasProposal",
    "AliasProposalBatch",
    "AliasProposer",
    "AliasStore",
    "LLMAliasMiner",
    "build_initial_alias_store",
]
