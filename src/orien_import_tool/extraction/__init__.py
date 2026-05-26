"""Pipeline B stage 2 — open extraction of components + failure modes.

Clean the operator narrative (TextLine3), then extract what it mentions
*before* any FMEA matching: failure modes deterministically (generic ISO /
alias vocabulary), components via an LLM. Linking to the equipment FMEA is a
later stage.
"""

from orien_import_tool.extraction.components import (
    ComponentExtractionBatch,
    LLMComponentExtractor,
    RowComponents,
)
from orien_import_tool.extraction.extractor import EntityExtractor
from orien_import_tool.extraction.failure_terms import (
    build_failure_vocabulary,
    tag_failure_modes,
)

__all__ = [
    "ComponentExtractionBatch",
    "EntityExtractor",
    "LLMComponentExtractor",
    "RowComponents",
    "build_failure_vocabulary",
    "tag_failure_modes",
]
