# Write-Time Dedup for Mirror KG

**Date**: 2026-07-07  
**Status**: Approved  
**Keys**: connection=(source_id, target_id), circuit=circuit_name

## Strategy

| Entity | Dedup Key | Merge Rule |
|--------|-----------|------------|
| Connection | `(source_region_candidate_id, target_region_candidate_id)` | Higher confidence wins, preserve both provenances |
| Circuit | `circuit_name` | Higher confidence wins, update fields, preserve provenance |

## Implementation

### Connection: `persist_connection_mirror_records`
- Before INSERT, SELECT existing by (source_id, target_id)
- If exists: update if new confidence > old; always merge provenance
- If not exists: INSERT

### Circuit: `_execute_connection_based_extraction` & region `run_pack`
- Already queries existing_map by circuit_name
- Enhance: merge provenance from both old and new records

### DB: Add unique index
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_conn_src_tgt 
ON mirror_region_connections(source_region_candidate_id, target_region_candidate_id);
```
