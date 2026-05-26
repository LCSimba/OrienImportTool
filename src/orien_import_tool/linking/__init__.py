"""Pipeline B stage 3 — link extracted spans to the FMEA / ISO 14224.

Deterministic: components match against the FMEA seed index, failure terms
resolve to ISO B.15, and equipment/section identifiers are filtered out. This
is where Pipeline B finally compares to the FMEA list.
"""

from orien_import_tool.linking.asset_ids import looks_like_asset_id
from orien_import_tool.linking.linker import (
    ComponentLinker,
    EntityLinker,
    FailureModeLinker,
)

__all__ = [
    "ComponentLinker",
    "EntityLinker",
    "FailureModeLinker",
    "looks_like_asset_id",
]
