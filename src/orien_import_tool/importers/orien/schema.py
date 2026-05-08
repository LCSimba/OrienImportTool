"""Constants describing the Orien Tactics ``Single Sheet Tactics`` export.

Anchored to the conveyor fixture
(``tests/fixtures/orien/SCHEMA.md``). Update with care — these values
double as a contract against the upstream Orien format.
"""

# --- Sheet names ----------------------------------------------------------------------

SHEET_DROPDOWN = "r8DropdownValues"
SHEET_DATA = "Single Sheet Tactics"
EXPECTED_SHEET_NAMES: tuple[str, ...] = (SHEET_DROPDOWN, SHEET_DATA)


# --- Header rows on the data sheet (0-indexed) ----------------------------------------

ROW_EXPORT_MARKER = 0
ROW_SHEET_TYPE_MARKER = 2
ROW_LOCATION = 5
ROW_TACTICS_MARKER = 6
ROW_MACHINE_HEADERS = 8
ROW_HUMAN_HEADERS = 9
FIRST_DATA_ROW = 10

EXPECTED_EXPORT_MARKER = "Orien Export"
EXPECTED_SHEET_TYPE_MARKER = "Single Sheet Tactics"
EXPECTED_TACTICS_MARKER = "tactics-single-sheet-import"


# --- Required column names on the data sheet ------------------------------------------
#
# These names appear on row 9 (machine-readable). Required columns are those the
# parser actively reads; presence of all 132 columns is asserted in the contract
# test, not here.

REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "makeChanges",
        "locationToken",
        "locationDescription",
        "structureRevision",
        "structureToken",
        "parentComponentDescription",
        "componentDescription",
        "function",
        "failure",
        "functionCategory",
        "functionType",
        "failureModeToken",
        "isRedundantYN",
        "what",
        "mechanismAndCause",
        "strategyType",
        "activityToken",
        "activityDescription",
        "activityType",
    }
)

# Custom-field columns follow this prefix and become entries in
# ``FailureMode.custom_attributes``.
FAILURE_MODE_CUSTOM_PREFIX = "Failure Mode.custom."
COST_CUSTOM_PATTERN = "CustomCost{slot}.custom."

# --- Slot counts (Orien denormalizes up to 5 line items per activity) ----------------

LABOUR_SLOTS = 5
MATERIAL_SLOTS = 5
COST_SLOTS = 5
