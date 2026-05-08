# ISO 14224 Reference Tables

Curated subset of ISO 14224 Annex B used as canonical reference data for the import tool. The CSVs in this folder are loaded into the canonical store on bootstrap and referenced by every Orien-to-ISO mapping.

## Tables

| File | Annex | Domain | Rows | Primary key |
|---|---|---|---|---|
| `ISO14224_Table_B2_FailureMechanisms.csv` | B.2 | How a failure occurred (mechanism level) | 38 | `sub_code` |
| `ISO14224_Table_B3_FailureCauses.csv` | B.3 | Root cause of failure | 21 | `sub_code` |
| `ISO14224_Table_B4_DetectionMethods.csv` | B.4 | How a failure was detected | 10 | `code_number` |
| `ISO14224_Table_B5_MaintenanceActivities.csv` | B.5 | Maintenance activity taxonomy | 12 | `code_number` |
| `ISO14224_Table_B15_FailureModeDescriptions.csv` | B.15 | Observable failure mode (what failed) | 29 | `failure_mode` |

## B15 — Failure Mode Descriptions

`failure_mode, description`

29 standardized observable modes: `Leak`, `No output`, `Output low`, `Output high`, `Erratic output`, `Seized/jammed/stuck`, `Blocked/plugged/restricted`, `Cracked/fractured/broken`, `Deformed`, `Worn`, `Corroded`, `Eroded`, `Overheating`, `Electrical short`, `Open circuit`, `Ground/isolation fault`, `No signal/indication/alarm`, `Faulty signal/indication/alarm`, `Out of adjustment/calibration drift`, `Spurious trip/shutdown`, `Software error`, `Physical damage`, `Contaminated`, `Loose/disconnected`, `Vibration (abnormal)`, `Cavitation`, `Burst/ruptured`, `Miscellaneous`, `Unknown`.

Used for: the **observable** half of every failure description ("the X" in "the X due to Y" — corresponds to Orien's leading verb in `mechanismAndCause`).

## B2 — Failure Mechanisms

`main_code, main_category, sub_code, sub_name, description`

Two-level hierarchy, same shape as B3:

- 1. Mechanical failure — General, Leakage, Vibration, Clearance/alignment failure, Deformation, Looseness, Sticking
- 2. Material failure — General, Cavitation, Corrosion, Erosion, Wear, Breakage, Fatigue, Overheating, Burst
- 3. Instrument failure — General, Control failure, No signal/indication/alarm, Faulty signal/indication/alarm, Out of adjustment, Software error, Common cause/Common mode failure
- 4. Electrical failure — General, Short circuiting, Open circuit, No power/voltage, Faulty power/voltage, Earth/isolation fault
- 5. External influence — General, Blockage/plugged, Contamination, Miscellaneous external influences
- 6. Miscellaneous — General, No cause found, Combined causes, Other, Unknown

`sub_code` (e.g. `1.1`, `2.4`, `3.6`) is the unambiguous primary key. The six `General` rows are now disambiguated as `1`, `2`, `3`, `4`, `5`, `6`.

Used for: the **mechanism** half of failure descriptions and as a coarser hint when only one of mode/mechanism is known.

## B3 — Failure Causes

`main_code, main_category, sub_code, sub_name, description`

Two-level hierarchy:

- 1. Design/manufacturing — General, Design error, Specification error, Manufacturing defect, Material defect, Installation error
- 2. Operation/maintenance — General, Operating error, Operating in wrong medium, Maintenance error, Test error
- 3. External — General, Contamination, Blockage, Impact, Environment, Natural event
- 4. Other — General, No cause found, Combined causes, Unknown

`sub_code` (e.g. `1.1`, `2.3`) is the unambiguous primary key. Use that, not `sub_name`.

Used for: the **root cause** half of failure descriptions (the "Y" in "X due to Y").

## B4 — Detection Methods

`code_number, method, description, examples`

10 methods: Failure-finding test, Condition monitoring, Scheduled inspection, Continuous monitoring, Scheduled maintenance, Demand, Operational observation, Maintenance observation, Other, Unknown.

Used for: **how a discovered failure was detected**. B4 is event metadata on a failure, not a property of a planned activity. Even when an Orien activity is itself a CM technique (Vibration Analysis, Thermography, Oil/Fluid Analysis, Ultrasonic Testing), the activity is still a B5 maintenance activity (B5:8 Test); B4 only enters the picture if that activity actually surfaced a failure and an SME records the detection method on the failure record.

## B5 — Maintenance Activities

`code_number, activity, description, examples, use, Corrective, Preventative`

12 activities: Replace, Repair, Modify, Adjust, Refit, Check, Service, Test, Inspection, Overhaul, Combination, Other.

Two extra columns flag applicability:

- `use` — `C` (corrective only), `P` (preventive only), or `C, P` (both).
- `Corrective` / `Preventative` — `X` if applicable, blank otherwise. Redundant with `use`; `use` is authoritative.

Used for: **what maintenance work was planned or performed**. Every Orien `activityCode` maps here. The B5 description and examples columns carry the synonyms (e.g. B5:4 Adjust includes "calibrate"; B5:5 Refit includes "lube, oil change"; B5:7 Service includes "Cleaning") so the mapping is unambiguous when the activity name itself doesn't match exactly.

## Natural Mappings — Orien → ISO 14224

The shape of the Orien data lines up cleanly with the ISO tables once we accept that one Orien field can carry multiple ISO codes:

| Orien field | ISO target(s) | Notes |
|---|---|---|
| `mechanismAndCause` ("X due to Y") | B15 (X) + B2 (X or Y) + B3 (Y) | Decompose at " due to " into mode/mechanism + cause. |
| `what` | B15 | When `mechanismAndCause` is blank or generic. |
| `strategyType` | (no direct ISO equivalent) | Carry as Orien-native attribute. |
| `activityCode` | B5 (always) | Use B5 description + examples for synonym matching; never B4. |
| `activityType` (Predictive / Preventative / Corrective / …) | B5.use | Cross-check predicted B5 mapping against Orien's stated activity type. |
| `criticalYN`, custom criticality | (no direct ISO equivalent) | Stays in canonical model only. |
| Detection method on a discovered failure (SME-entered, not from Orien export) | B4 | Separate fact; never lives on the activity. |

### Worked examples (from this fixture's vocabulary)

| Orien `mechanismAndCause` | B15 | B2 | B3 |
|---|---|---|---|
| Wears due to Mechanical overload | Worn | Wear | 2.1 Operating error |
| Corrodes due to Chemical attack | Corroded | Corrosion | 3.4 Environment |
| Cracks due to Cyclic loading (thermal/mechanical) | Cracked/fractured/broken | Fatigue | 1.1 Design error / 2.1 Operating error |
| Loses Preload due to Vibration | Loose/disconnected | Vibration | 4.2 Combined causes |
| Open-Circuit due to Electrical overload | Open circuit | Open circuit | 2.1 Operating error |
| Blocks due to Contamination | Blocked/plugged/restricted | Contamination | 3.1 Contamination |
| Overheats/Melts due to Lack of lubrication | Overheating | Wear (or Overheating) | 2.3 Maintenance error |

These mappings will be SME-confirmed during enrichment, not auto-applied. The mapping store records the proposer (`rule | llm | sme`) and confidence on every row.

### Worked examples — Orien `activityCode` → B5

Every entry resolves cleanly to a B5 row using either the activity name or B5's `description` / `examples` column. No B4 fallback.

| Orien `activityCode` | B5 code | B5 activity | Justification |
|---|---|---|---|
| Adjust | 4 | Adjust | direct |
| Calibrate | 4 | Adjust | B5:4 examples include "calibrate" |
| Check | 6 | Check | direct |
| Clean | 7 | Service | B5:7 examples include "Cleaning" |
| Fluid Analysis | 9 | Inspection | B5:9 — condition monitoring is a non-destructive inspection technique |
| Inspection | 9 | Inspection | direct |
| Lube | 5 | Refit | B5:5 examples include "lube, oil change" |
| Measure | 9 | Inspection | B5:9 — measurement is a condition assessment (thickness / clearance / runout) |
| Oil Analysis | 9 | Inspection | B5:9 — condition monitoring is a non-destructive inspection technique |
| Operate | 12 | Other | operating is not maintenance work |
| Repair | 2 | Repair | direct |
| Replace | 1 | Replace | direct |
| Statutory | 8 | Test | B5:8 — regulatory function/performance test |
| Test | 8 | Test | direct |
| Thermography | 9 | Inspection | B5:9 — condition monitoring is a non-destructive inspection technique |
| Ultrasonic Testing | 9 | Inspection | B5:9 — condition monitoring is a non-destructive inspection technique |
| Vibration Analysis | 9 | Inspection | B5:9 — condition monitoring is a non-destructive inspection technique |

## Bootstrap loading

On first start, the importer loads each CSV into its corresponding `Iso14224*` reference table. The tables are immutable from the application — updates land via a new CSV in this folder and a versioned reload, never via UI edits. Mappings produced against an older version remain valid because they reference the table version used at the time of mapping.

## Open issues

1. **B5 redundant columns.** `Corrective` and `Preventative` duplicate `use`. The loader picks `use` and ignores the others; this is documented to avoid silent drift.
2. **B4 Unknown row has empty `examples`.** Loader must accept empty cells without choking.
3. **Smart quotes in B2.** Lines 3 and 4 contain typographic quotes (`“` `”`). The loader must read UTF-8 and treat them as ordinary characters, not collapse them to ASCII.
