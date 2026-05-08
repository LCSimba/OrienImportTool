# ISO 14224 Reference Tables

Curated subset of ISO 14224 Annex B used as canonical reference data for the import tool. The CSVs in this folder are loaded into the canonical store on bootstrap and referenced by every Orien-to-ISO mapping.

## Tables

| File | Annex | Domain | Rows | Primary key |
|---|---|---|---|---|
| `ISO14224_Table_B2_FailureMechanisms.csv` | B.2 | How a failure occurred (mechanism level) | 38 | `failure_mechanism` (see note) |
| `ISO14224_Table_B3_FailureCauses.csv` | B.3 | Root cause of failure | 21 | `sub_code` |
| `ISO14224_Table_B4_DetectionMethods.csv` | B.4 | How a failure was detected | 10 | `code_number` |
| `ISO14224_Table_B5_MaintenanceActivities.csv` | B.5 | Maintenance activity taxonomy | 12 | `code_number` |
| `ISO14224_Table_B15_FailureModeDescriptions.csv` | B.15 | Observable failure mode (what failed) | 29 | `failure_mode` |

## B15 — Failure Mode Descriptions

`failure_mode, description`

29 standardized observable modes: `Leak`, `No output`, `Output low`, `Output high`, `Erratic output`, `Seized/jammed/stuck`, `Blocked/plugged/restricted`, `Cracked/fractured/broken`, `Deformed`, `Worn`, `Corroded`, `Eroded`, `Overheating`, `Electrical short`, `Open circuit`, `Ground/isolation fault`, `No signal/indication/alarm`, `Faulty signal/indication/alarm`, `Out of adjustment/calibration drift`, `Spurious trip/shutdown`, `Software error`, `Physical damage`, `Contaminated`, `Loose/disconnected`, `Vibration (abnormal)`, `Cavitation`, `Burst/ruptured`, `Miscellaneous`, `Unknown`.

Used for: the **observable** half of every failure description ("the X" in "the X due to Y" — corresponds to Orien's leading verb in `mechanismAndCause`).

## B2 — Failure Mechanisms

`failure_mechanism, description`

38 mechanisms grouped by implicit category (Mechanical, Material, Instrumentation, Electrical, External, Misc). The CSV does **not** carry the category column, so the value `General` repeats six times — once per group. Open issue: the parser must either (a) be given an updated CSV with a `category` column, or (b) infer category by row ordinal. See **Open issues** below.

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

Used for: the canonical detection-method axis of the FMEA. Some Orien activityCodes (Vibration Analysis, Thermography, Oil/Fluid Analysis, Ultrasonic Testing) actually describe detection techniques and map here, not to B5.

## B5 — Maintenance Activities

`code_number, activity, description, examples, use, Corrective, Preventative`

12 activities: Replace, Repair, Modify, Adjust, Refit, Check, Service, Test, Inspection, Overhaul, Combination, Other.

Two extra columns flag applicability:

- `use` — `C` (corrective only), `P` (preventive only), or `C, P` (both).
- `Corrective` / `Preventative` — `X` if applicable, blank otherwise. Redundant with `use`; `use` is authoritative.

Used for: the maintenance-activity axis. Most Orien activityCodes map here directly.

## Natural Mappings — Orien → ISO 14224

The shape of the Orien data lines up cleanly with the ISO tables once we accept that one Orien field can carry multiple ISO codes:

| Orien field | ISO target(s) | Notes |
|---|---|---|
| `mechanismAndCause` ("X due to Y") | B15 (X) + B2 (X or Y) + B3 (Y) | Decompose at " due to " into mode/mechanism + cause. |
| `what` | B15 | When `mechanismAndCause` is blank or generic. |
| `strategyType` | (no direct ISO equivalent) | Carry as Orien-native attribute. |
| `activityCode` | B5 mostly; B4 for condition-monitoring techniques | Branch on activity nature. |
| `activityType` (Predictive / Preventative / Corrective / …) | B5.use | Cross-check predicted B5 mapping against Orien's stated activity type. |
| `criticalYN`, custom criticality | (no direct ISO equivalent) | Stays in canonical model only. |

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

## Bootstrap loading

On first start, the importer loads each CSV into its corresponding `Iso14224*` reference table. The tables are immutable from the application — updates land via a new CSV in this folder and a versioned reload, never via UI edits. Mappings produced against an older version remain valid because they reference the table version used at the time of mapping.

## Open issues

1. **B2 category column missing.** Six rows share the value `General`. The parser must either be given a `category` column or infer category from row ordinal. Recommended: re-emit the CSV with a `category` column (`Mechanical`, `Material`, `Instrumentation`, `Electrical`, `External`, `Misc`) so each row is unambiguous.
2. **B5 redundant columns.** `Corrective` and `Preventative` duplicate `use`. The loader picks `use` and ignores the others; this is documented to avoid silent drift.
3. **B4 Unknown row has empty `examples`.** Loader must accept empty cells without choking.
4. **Smart quotes in B2.** Lines 3 and 4 contain typographic quotes (`“` `”`). The loader must read UTF-8 and treat them as ordinary characters, not collapse them to ASCII.
