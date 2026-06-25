# Final KG Export Format (Step 8.17)

Offline export from `final_*` internal formal knowledge layer. **Not** external DB sync.

## Directory structure

```
data/exports/final_kg/<export_id>/
  manifest.json
  nodes.jsonl
  edges.jsonl
  nodes.csv
  edges.csv
  neo4j_nodes.csv
  neo4j_relationships.csv
  evidence.jsonl          # when include_evidence=true
  provenance.jsonl        # when include_provenance=true
  README.md               # when include_readme=true
```

`export_id` format: `EXP-YYYYMMDD-HHMMSS-<8hex>`

## manifest.json schema

```json
{
  "export_id": "EXP-20260615-120000-a1b2c3d4",
  "created_at": "2026-06-15T12:00:00+00:00",
  "created_by": "local_api",
  "export_label": null,
  "scope": {},
  "formats": ["jsonl", "csv", "neo4j_csv"],
  "target_types": ["circuit", "projection"],
  "counts": { "nodes": 0, "edges": 0, "evidence": 0, "provenance": 0 },
  "files": { "nodes_jsonl": "nodes.jsonl", "manifest": "manifest.json" },
  "schema_version": "final_macro_clinical_export_v1",
  "app_version": "4.6.0-mvp2-final-kg-export",
  "warnings": [],
  "boundaries": {
    "write_final": false,
    "write_mirror": false,
    "write_kg": false,
    "write_external_db": false,
    "llm_called": false
  }
}
```

## nodes.jsonl

One JSON object per line:

```json
{
  "node_id": "final:circuit:550e8400-e29b-41d4-a716-446655440000",
  "labels": ["Circuit", "FinalObject"],
  "target_type": "circuit",
  "final_id": "550e8400-e29b-41d4-a716-446655440000",
  "final_uid": "final_macro_clinical:circuit:...",
  "label": "limbic circuit",
  "properties": {
    "source_atlas": "Macro96",
    "granularity_level": "macro",
    "confidence": 0.9,
    "final_status": "active"
  },
  "provenance": {
    "source_mirror_type": "circuit",
    "source_mirror_id": "...",
    "promotion_run_id": "..."
  }
}
```

BrainRegion example:

```json
{
  "node_id": "candidate_region:...",
  "labels": ["BrainRegion"],
  "target_type": "brain_region",
  "label": "Amygdala",
  "properties": { "region_name": "...", "source_atlas": "Macro96" },
  "provenance": {}
}
```

## edges.jsonl

```json
{
  "edge_id": "edge:CIRCUIT_HAS_STEP:final:circuit:...:final:circuit_step:...:1",
  "type": "CIRCUIT_HAS_STEP",
  "source": "final:circuit:...",
  "target": "final:circuit_step:...",
  "label": "has step",
  "properties": { "step_order": 1 },
  "provenance": { "source_mirror_id": "...", "promotion_run_id": "..." }
}
```

## CSV columns

**nodes.csv**: node_id, labels, target_type, final_id, final_uid, label, source_atlas, source_version, granularity_level, granularity_family, confidence, final_status, source_mirror_type, source_mirror_id, promotion_run_id, created_at, properties_json, provenance_json

**edges.csv**: edge_id, type, source, target, label, source_atlas, source_version, granularity_level, granularity_family, confidence, source_mirror_type, source_mirror_id, promotion_run_id, properties_json, provenance_json

## Neo4j-compatible CSV

**neo4j_nodes.csv**: :ID, :LABEL, name, target_type, final_id, final_uid, source_atlas, source_version, granularity_level, granularity_family, confidence:float, final_status, source_mirror_type, source_mirror_id, promotion_run_id, properties_json

**neo4j_relationships.csv**: :START_ID, :END_ID, :TYPE, edge_id, label, source_atlas, source_version, granularity_level, granularity_family, confidence:float, source_mirror_type, source_mirror_id, promotion_run_id, properties_json

## Node labels

BrainRegion, Circuit, CircuitStep, CircuitFunction, Projection, ProjectionFunction, CircuitProjectionMembership, RegionFunction, Triple, Evidence, FinalObject, Function

## Relationship types

REGION_HAS_FUNCTION, REGION_PARTICIPATES_IN_CIRCUIT, CIRCUIT_HAS_STEP, STEP_HAS_REGION, CIRCUIT_CONTAINS_PROJECTION, PROJECTION_BELONGS_TO_CIRCUIT, CIRCUIT_HAS_MEMBERSHIP, MEMBERSHIP_HAS_PROJECTION, MEMBERSHIP_SOURCE_STEP, MEMBERSHIP_TARGET_STEP, PROJECTION_SOURCE_REGION, PROJECTION_TARGET_REGION, PROJECTION_HAS_FUNCTION, CIRCUIT_HAS_FUNCTION, OBJECT_HAS_EVIDENCE, TRIPLE_SUBJECT, TRIPLE_OBJECT

## Boundary statement

- This export **does not** write to Neo4j.
- This export **does not** write to `kg_*` tables.
- This export **does not** sync to external NeuroGraphIQ_KG_V3 formal database.
- User must manually review files before any external import.
