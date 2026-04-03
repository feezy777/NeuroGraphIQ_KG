# Major Pipeline Runbook

## 1. Scope
This runbook covers:
- `anatomy + major` preview workflow
- major load workflow
- local IDE-style dashboard operation

`sub/allen` and real crawler are not in this phase.

## 2. Prerequisites
- Python >= 3.10
- PostgreSQL reachable from local machine
- Runtime config available at `configs/local/runtime.local.yaml`
- Input Excel available (`Sheet1` with expected headers)

## 3. Schema Rebuild Order
Use:
```powershell
python -m scripts.pipeline.rebuild_schema
```

Equivalent SQL execution order:
1. `drop schema neurokg cascade`
2. `sql/schema/001_create_schema.sql`
3. `sql/schema/002_create_tables_anatomy.sql`
4. `sql/schema/003_create_tables_region.sql`
5. `sql/schema/004_create_tables_connection.sql`
6. `sql/schema/005_create_tables_circuit.sql`
7. `sql/schema/006_create_tables_evidence.sql`
8. `sql/schema/007_create_tables_relation.sql`
9. `sql/schema/008_create_tables_extension.sql`
10. `sql/schema/009_create_indexes.sql`
11. `sql/schema/010_create_triggers.sql`
12. `sql/seeds/001_seed_test_data.sql`
13. `sql/seeds/002_seed_reference_data.sql`

## 4. Preview and Load Contracts
### Preview
Sequence:
1. `extract_anatomy`
2. `extract_major_regions`
3. `validate_major_regions`
4. `extract_major_circuits`
5. `validate_major_circuits`
6. `extract_major_connections` (derived + direct + crosscheck)
7. `validate_major_connections`
8. `export_reports`

Output root:
`artifacts/ui_runs/<run_id>/`

### Load
Sequence:
1. `load_anatomy`
2. `load_major_regions`
3. `load_major_connections`
4. `load_major_circuits`

Load consumes validated outputs from one preview run.

## 5. Local Dashboard
Start:
```powershell
python -m scripts.ui.run_dashboard
```

URL:
`http://127.0.0.1:8899`

Main controls:
- `Import Excel`: preview table headers/first rows
- `Rebuild Schema`: rebuild and seed DB
- `Run Preview`: run full preview pipeline
- `Load To DB`: load current preview run
- `Open Reports`: show report output path in log panel

## 6. Validation and Status
Crosscheck statuses in `major_connection.validation_status`:
- `cross_pass_unverified`
- `cross_fail_unverified`

FK-unmappable rows stay in rejected files and are not loaded.

## 7. Failure Handling
- Fail-fast at stage level
- Stage reports are persisted under preview artifacts
- UI shows failed stage + error message in bottom log panel

Check:
- `artifacts/ui_runs/<run_id>/major_preview_summary.json`
- `artifacts/ui_runs/<run_id>/major_load_summary.json`
- `logs/<run_id>.log`

