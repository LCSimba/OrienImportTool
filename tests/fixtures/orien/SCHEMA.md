# Orien Tactics — Single Sheet Tactics Export Schema

Authoritative description of the export format the importer must parse. Derived from `2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx`. This document is the parser contract; new fixtures should refine it, not contradict it without note.

## Workbook

`.xlsx` with two sheets:

| Sheet | Purpose |
|---|---|
| `r8DropdownValues` | Controlled-vocabulary lists (one per data-column with Excel validation) |
| `Single Sheet Tactics` | FMEA + maintenance tactics data, denormalized |

## Sheet: `Single Sheet Tactics`

### Metadata header (rows 1-10, 1-indexed)

| Row | Purpose |
|---|---|
| 1 | Marker `Orien Export` (col A) |
| 2 | App URL + import-back instructions |
| 3 | Sheet-type identifier `Single Sheet Tactics` |
| 4 | _blank_ |
| 5 | Note: "These first 10 rows contain header data that must be present for this sheet to be imported back into Orien" |
| 6 | Location row — `locationToken`, `locationDescription`, `language` (e.g. `en`) |
| 7 | Marker `tactics-single-sheet-import`, export datetime, then key/value pairs: `location`, `revision`, `componentLibrary` |
| 8 | _blank_ |
| 9 | **Machine-readable column names (camelCase)** — use these to parse |
| 10 | Human-readable column headers (display only) |

The parser must:
- Assert row 1 starts with `Orien Export`.
- Assert row 3 equals `Single Sheet Tactics`.
- Extract `locationToken`, `locationDescription`, `language` from row 6.
- Extract export datetime, structure revision, and `componentLibrary` flag from row 7.
- Use row 9 (machine names) as the column index. Treat row 10 as advisory.

### Data rows (row 11+)

132 columns. Single fixture: 752 data rows. The sheet is denormalized — each row is one `(location, component, function, failure, failure_mode, activity)` tuple, with up to 5 labour, 5 material, and 5 cost line-items inline. Earlier-level fields repeat as later levels expand; many fields blank when later levels are not yet defined.

Columns grouped by purpose:

#### Identity / hierarchy
`makeChanges`, `locationToken`, `locationDescription`, `locationMake`, `locationModel`, `structureRevision`, `structureToken`, `parentComponentDescription`, `componentDescription`, `make`, `model`, `comments`, `sortPosition`, `componentStatus`, `componentRevision`, `structureStatus`, `isReference`

#### Function / failure
`function`, `failure`, `functionCategory`, `functionType`

#### Failure mode
`failureModeToken`, `isRedundantYN`, `what`, `mechanismAndCause`, `strategyType`, `notes`, `eta`, `beta`, `gamma`, `etaUnit`

#### Failure-mode custom fields
Naming pattern: `Failure Mode.custom.<Name>`. Observed:
`Failure Mode.custom.Justification`, `Failure Mode.custom.Justification Category`, `Failure Mode.custom.Production per Hour`, `Failure Mode.custom.PF Interval`

#### Allocation / replacement
`allocationType`, `isReplacement`, `isDominantReplacement`

#### Activity
`activityToken`, `activityDescription`, `activityCode`, `activityType`, `frequency`, `unit`, `budgetType`, `linkedActivityDescription`, `constraint`, `acceptableLimits`, `conditionalComments`, `consequences`, `origin`, `accessTimeHours`, `unscheduledOverheadHours`, `criticalYN`, `tacticReviewPerformYN`, `tacticReviewPeriodDays`, `taskColour`

#### Labour — 5 slots
`labourDescription{1..5}`, `work{1..5}`, `required{1..5}`

#### Materials — 5 slots
`materialDescription{1..5}`, `materialPartNumber{1..5}`, `materialStockCode{1..5}`, `materialPlantCode{1..5}`, `materialQuantity{1..5}`

#### Costs — 5 slots
`costDescription{1..5}`, `costType{1..5}`, `expenseElement{1..5}`, `quantity{1..5}`, `totalCost{1..5}`, `currency{1..5}`, `CustomCost{1..5}.custom.<Name>` (e.g. `Condition Type`)

### Row classes observed

1. **Component-only** — component populated, no function/failure (~rare).
2. **Component + function** — function/failure free text, no `failureModeToken`.
3. **Component + function + failure mode** — `failureModeToken`, `what`, `mechanismAndCause`, `strategyType` populated; no activity.
4. **Full** — all of the above plus an activity (with optional labour/material/cost slots).

### Tokens

`locationToken`, `structureToken`, `failureModeToken`, `activityToken` are stable, base64-looking UUIDs that survive re-exports. They are the natural keys for idempotent re-import (FR-1.4) and for diffing changes.

### Normalisation the parser must perform

Group denormalized rows back to:

- **Equipment** — 1 per `locationToken`.
- **ComponentTree** — `(parentComponentDescription → componentDescription)` deduplicated, ordered by `sortPosition`.
- **Function** — unique `(component, function)` text pairs.
- **FunctionalFailure** — unique `(function, failure)` text pairs.
- **FailureMode** — unique `failureModeToken`. Custom-field columns flatten into a JSONB `custom` map.
- **Activity** — unique `activityToken`, many per FailureMode. Labour/material/cost slots unfold into 1..5 line items each, dropping empty slots.

## Sheet: `r8DropdownValues`

Each row is a validation list bound to a column on the data sheet, in roughly the order those columns appear.

| Row | Vocabulary (n) | Bound column(s) |
|---|---|---|
| 1 | Y/N (2) | `makeChanges` |
| 2 | Manufacturers (25) | `locationMake` |
| 3 | Equipment models (158) | `locationModel` |
| 4 | Consequence categories (11) | `functionCategory` |
| 5 | Function types (5) | `functionType` |
| 6 | Y/N (2) | `isRedundantYN` |
| 7 | Mechanism + cause failure modes (73) | `mechanismAndCause` |
| 8 | Strategy types (5) | `strategyType` |
| 9 | Frequency units (10) | `etaUnit` |
| 10 | Allocation types (10) | `allocationType` |
| 11 | Activity types (6) | `activityType` |
| 12 | Y/N | `isReplacement` |
| 13 | Y/N | `isDominantReplacement` |
| 14 | Activity codes (17) | `activityCode` |
| 15 | Frequency units (10) | `unit` |
| 16 | Budget types (3) | `budgetType` |
| 17 | Operational state (3) | `constraint` |
| 18 | Y/N | `criticalYN` |
| 19 | Y/N | `tacticReviewPerformYN` |
| 20-24 | Labour roles (219, identical) | `labourDescription{1..5}` |
| 25-39 | Cost-slot triples (kind, OPEX-flag, source) repeated per cost slot | cost-slot validation |

### Why the dropdown sheet matters

- Row 7 (mechanism+cause) is the **canonical failure-mode taxonomy** — direct supervised seeds for FR-5.4 / FR-7.4.
- Row 14 (activity codes: Adjust, Calibrate, Check, Clean, Inspection, Lube, Repair, Replace, Test, Vibration Analysis…) maps cleanly to ISO 14224 maintenance activity codes.
- Row 20's labour-role list shows real-world entry noise — `"Electrician."`, `"ELECTRICAL ELECTRICIAN"`, `"AA- A 20 -Electrician"`, `"b"`, `"dam"` — concrete justification for the alias store (FR-5.1) before we even reach operator downtime text.
- Manufacturer + model lists supply equipment master-data for normalization.

## Parser Contract (test-driven)

Before any parser code, the contract test against this fixture must assert:

- `wb.sheetnames == ['r8DropdownValues', 'Single Sheet Tactics']`
- Row 1 starts with `Orien Export`; row 3 == `Single Sheet Tactics`.
- Row 9 has 132 column names; first column is `makeChanges`; required tokens (`locationToken`, `failureModeToken`, `activityToken`) are present.
- `locationToken` from row 6 matches the `locationToken` in every data row.
- 752 data rows.
- Mechanism+cause values appearing in data are a subset of the row-7 dropdown vocabulary.

The parser is then written to make this test pass.

## Fixture statistics (this export)

- 1 location (`4FC025 - CONVEYOR [4F-Belt] - TRUNK`), 77 components forming a 2-level tree (7 top-level + 70 children). Top-level: Conveyor Belt Assembly, Conveyor Drive System, Conveyor Structure, Conveyor Take-Up System, Dust suppresion system, Electrical System, Instrumentation System.
- 752 data rows; 735 with failure mode; 737 with activity.
- 21 distinct `mechanismAndCause` values used (of 73 in vocabulary).
- Strategy mix — Condition Based: 692, Fixed Time: 35, Fault Find Interval: 8.
- Function-type mix — Primary: 603, Secondary: 146, no Protective or Superfluous.
- Weibull (`eta`/`beta`/`gamma`) populated on ~25% of rows.
- `activityCode` empty in this export (column present, vocabulary present, no data).
- `costDescription*` empty in this export.
- 8 rows carry `Failure Mode.custom.Justification`.

## Known unknowns (collect more fixtures to resolve)

- Multi-location exports — what does row 6 look like and does `locationToken` vary per row?
- `componentLibrary=true` exports — content differences vs `false`.
- Whether `activityCode` and cost columns are universally empty or just for this export.
- Whether the row-9 column order is stable across Orien versions.
- Multi-language exports — does `language` ever differ from `en`, and does that change column-name spelling?
