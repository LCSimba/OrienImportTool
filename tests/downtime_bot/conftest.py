"""Shared fixtures for the downtime voice-bot tests.

A small but realistic single-conveyor FMEA so the taxonomy has real
components, failure modes, and "X due to Y" causes to drive the bot with.
"""

from __future__ import annotations

import pytest

from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)
from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy


def _component(token: str, description: str, parent: str, fm_token: str,
               what: str, mechanism_and_cause: str) -> Component:
    return Component(
        token=token,
        description=description,
        parent_description=parent,
        functions=[
            Function(
                description=f"{description} function",
                failures=[
                    FunctionalFailure(
                        description=f"{description} fails",
                        failure_modes=[
                            FailureMode(
                                token=fm_token,
                                what=what,
                                mechanism_and_cause=mechanism_and_cause,
                            )
                        ],
                    )
                ],
            )
        ],
    )


@pytest.fixture
def conveyor() -> Equipment:
    return Equipment(
        token="CONV1",
        description="Conveyor",
        make="ACME",
        model="CV-200",
        components=[
            _component(
                "C-MOTOR", "Drive motor", "Drive assembly", "FM-MOT-1",
                "Motor overheats", "Winding overheats due to overload",
            ),
            _component(
                "C-BEARING", "Head pulley bearing", "Head pulley", "FM-BRG-1",
                "Bearing seized", "Bearing seizes due to contamination",
            ),
            _component(
                "C-BELT", "Conveyor belt", "Belt", "FM-BELT-1",
                "Belt torn", "Belt tears due to misalignment",
            ),
        ],
    )


@pytest.fixture
def taxonomy(conveyor: Equipment) -> CaptureTaxonomy:
    return CaptureTaxonomy(equipment=[conveyor], iso=None)
