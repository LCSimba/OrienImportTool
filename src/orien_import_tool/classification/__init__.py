"""Downtime classification pipeline.

The first-cut classifier is alias-based: token overlap between the downtime
text and a seed index built from the canonical Equipment / FMEA tree. ML and
LLM-based classifiers slot in behind the same ``classify(event)`` interface.
"""

from orien_import_tool.classification.alias_classifier import AliasClassifier
from orien_import_tool.classification.preprocessor import normalise, tokenise
from orien_import_tool.classification.seeds import SeedIndex, build_seed_index

__all__ = [
    "AliasClassifier",
    "SeedIndex",
    "build_seed_index",
    "normalise",
    "tokenise",
]
