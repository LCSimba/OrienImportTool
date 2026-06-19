"""Turn the canonical FMEA into the option sets each slot offers.

The bot never invents reliability vocabulary — it constrains the technician to
what the FMEA already knows about the machine they picked. ``CaptureTaxonomy``
indexes one or more :class:`~orien_import_tool.domain.fmea.Equipment` trees and
answers, per slot:

* which **machine types** exist (one per equipment tree),
* which **components** belong to a machine,
* which **failure modes** are recorded for a component (with the generic ISO
  14224 B.15 list as a fallback when the FMEA has none),
* which **root causes** the FMEA associates with a component (parsed from the
  Orien ``mechanism_and_cause`` "X due to Y" strings, plus ISO B.3 causes), and
* **position hints** mined from the component descriptions.

An optional :class:`~orien_import_tool.iso14224.Iso14224ReferenceSet` widens the
failure-mode and root-cause vocabularies beyond what any single FMEA contains.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orien_import_tool.classification.preprocessor import normalise
from orien_import_tool.domain.fmea import Component, Equipment
from orien_import_tool.downtime_bot.matching import Option
from orien_import_tool.iso14224 import Iso14224ReferenceSet

# Position keywords worth surfacing as hints when they appear in component text.
# Functional position on a machine (ISO 14224 has no dedicated table for it).
_POSITION_KEYWORDS: tuple[str, ...] = (
    "drive", "non-drive", "non drive", "free", "fixed", "head", "tail",
    "return", "snub", "inlet", "outlet", "discharge", "feed", "left", "right",
    "top", "bottom", "upper", "lower", "front", "rear", "near", "far",
    "north", "south", "east", "west", "primary", "secondary", "inboard",
    "outboard", "no 1", "no 2", "no1", "no2",
)


def _split_cause(mechanism_and_cause: str) -> str:
    """Pull the root-cause clause out of an Orien "X due to Y" string.

    Returns the ``Y`` (cause) clause, title-stripped. When there is no "due
    to" the whole string is the best available cause description.
    """
    text = mechanism_and_cause.strip()
    if not text:
        return ""
    lowered = text.casefold()
    marker = " due to "
    idx = lowered.find(marker)
    if idx != -1:
        return text[idx + len(marker):].strip(" .")
    return text.strip(" .")


def _dedup(options: list[Option]) -> list[Option]:
    """Drop options whose value normalises to one already seen (first wins)."""
    seen: set[str] = set()
    out: list[Option] = []
    for opt in options:
        key = normalise(opt.value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(opt)
    return out


@dataclass
class CaptureTaxonomy:
    """Slot-scoped option provider built from FMEA equipment trees."""

    equipment: list[Equipment] = field(default_factory=list)
    iso: Iso14224ReferenceSet | None = None
    # Indexes built in __post_init__.
    _components: dict[str, dict[str, Component]] = field(default_factory=dict, init=False)
    _component_owner: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for eq in self.equipment:
            self._components[eq.token] = {c.token: c for c in eq.components}
            for c in eq.components:
                self._component_owner[c.token] = eq.token

    # --- machine type -----------------------------------------------------------

    def machine_types(self) -> list[Option]:
        """One option per loaded equipment tree."""
        options = []
        for eq in self.equipment:
            aliases = tuple(a for a in (eq.make, eq.model, eq.token) if a)
            options.append(
                Option(value=eq.description or eq.token, token=eq.token, aliases=aliases)
            )
        return _dedup(options)

    # --- component --------------------------------------------------------------

    def components(self, equipment_token: str) -> list[Option]:
        """Components belonging to one machine type."""
        owned = self._components.get(equipment_token, {})
        options = [
            Option(
                value=c.description or c.token,
                token=c.token,
                aliases=tuple(a for a in (c.parent_description, c.make, c.model) if a),
            )
            for c in owned.values()
        ]
        return _dedup(options)

    # --- failure mode -----------------------------------------------------------

    def failure_modes(self, component_token: str) -> list[Option]:
        """Failure modes recorded for a component.

        Prefers the component's own FMEA modes; falls back to the generic ISO
        14224 B.15 list when the component has none (or no FMEA is loaded).
        """
        component = self._component(component_token)
        options: list[Option] = []
        if component is not None:
            for fm, function_desc, failure_desc in _iter_failure_modes(component):
                label = fm.what or failure_desc or function_desc
                if not label:
                    continue
                cause = _split_cause(fm.mechanism_and_cause)
                aliases = tuple(a for a in (failure_desc, cause) if a)
                options.append(Option(value=label, token=fm.token, aliases=aliases))
        options = _dedup(options)
        if options:
            return options
        return self.generic_failure_modes()

    def generic_failure_modes(self) -> list[Option]:
        """ISO 14224 B.15 observable failure modes, when reference data is loaded."""
        if self.iso is None:
            return []
        return _dedup(
            [Option(value=fm.description, token=fm.code) for fm in self.iso.failure_modes.values()]
        )

    # --- root cause -------------------------------------------------------------

    def root_causes(self, component_token: str) -> list[Option]:
        """Root causes the FMEA links to a component, plus ISO B.3 causes.

        The component-specific causes (parsed from ``mechanism_and_cause``)
        come first because they are the likeliest answers for that hardware;
        the generic ISO causes follow as a broader safety net.
        """
        component = self._component(component_token)
        options: list[Option] = []
        if component is not None:
            for fm, _function_desc, _failure_desc in _iter_failure_modes(component):
                cause = _split_cause(fm.mechanism_and_cause)
                if cause:
                    options.append(Option(value=cause, token=fm.token))
        options.extend(self.generic_root_causes())
        return _dedup(options)

    def generic_root_causes(self) -> list[Option]:
        """ISO 14224 B.3 failure causes (sub-categories), when loaded."""
        if self.iso is None:
            return []
        return _dedup(
            [
                Option(value=c.description or c.sub_name, token=c.sub_code)
                for c in self.iso.failure_causes.values()
                if not c.is_general
            ]
        )

    # --- position ---------------------------------------------------------------

    def position_hints(self, component_token: str) -> list[str]:
        """Position keywords found in this component and its siblings' text.

        Position is free-text (no FMEA field encodes it), but offering the
        machine's own vocabulary — "drive end", "head", "tail" — guides the
        technician toward a consistent answer.
        """
        component = self._component(component_token)
        if component is None:
            return []
        equipment_token = self._component_owner.get(component_token, "")
        siblings = self._components.get(equipment_token, {}).values()
        haystack = " ".join(
            normalise(f"{c.description} {c.parent_description}") for c in siblings
        )
        hints: list[str] = []
        for keyword in _POSITION_KEYWORDS:
            if normalise(keyword) in haystack and keyword not in hints:
                hints.append(keyword)
        return hints

    # --- internals --------------------------------------------------------------

    def _component(self, component_token: str) -> Component | None:
        owner = self._component_owner.get(component_token)
        if owner is None:
            return None
        return self._components[owner].get(component_token)


def _iter_failure_modes(component: Component):
    """Yield ``(FailureMode, function_description, failure_description)`` triples."""
    for function in component.functions:
        for failure in function.failures:
            for fm in failure.failure_modes:
                yield fm, function.description, failure.description
