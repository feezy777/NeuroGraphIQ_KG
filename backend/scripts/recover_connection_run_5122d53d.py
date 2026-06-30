#!/usr/bin/env python3
"""
一次性恢复脚本：检查并恢复 extraction item 的连接数据到 mirror_region_connections。

用法:
  cd backend
  .venv/Scripts/python.exe scripts/recover_connection_run_5122d53d.py --dry-run
  .venv/Scripts/python.exe scripts/recover_connection_run_5122d53d.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

import asyncpg

WORKFLOW_RUN_ID = "5122d53d-c023-4ae9-86b5-ef7b91d4e453"
DB_URL = "postgresql://postgres:postgres@127.0.0.1:5432/neurographiq_kg_v3_mvp1_e2e"
MIN_CONFIDENCE = 0.3  # Only recover connections at or above this confidence


async def get_candidate_labels(db: asyncpg.Connection, candidate_ids: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not candidate_ids:
        return labels
    rows = await db.fetch(
        "SELECT id, cn_name, en_name FROM candidate_brain_regions WHERE id = ANY($1::uuid[])",
        candidate_ids,
    )
    for r in rows:
        labels[str(r["id"])] = r["cn_name"] or r["en_name"] or str(r["id"])[:8]
    return labels


async def run(dry_run: bool = True) -> dict:
    db = await asyncpg.connect(DB_URL)
    result = {
        "workflow_run_id": WORKFLOW_RUN_ID,
        "dry_run": dry_run,
        "source_table": None,
        "total_extracted": 0,
        "existing_mirror": 0,
        "low_quality_skipped": 0,
        "recovered": 0,
        "skipped_existing": 0,
        "failed": 0,
        "errors": [],
    }

    # ── Step 1: Identify the record type ───────────────────────────────────
    print("=" * 60)
    print(f"Investigating ID: {WORKFLOW_RUN_ID}")
    print("=" * 60)

    item = await db.fetchrow(
        "SELECT id, run_id, status, parsed_response_json, normalized_output_json "
        "FROM llm_extraction_items WHERE id = $1",
        WORKFLOW_RUN_ID,
    )
    if not item:
        print(f"\n[ERROR] ID not found in llm_extraction_items")
        result["errors"].append("ID not found")
        await db.close()
        return result

    print(f"\n[INFO] ID belongs to: llm_extraction_items (item_id)")
    result["source_table"] = "llm_extraction_items (item_id)"
    run_id = str(item["run_id"])

    erun = await db.fetchrow(
        "SELECT id, task_type, status, input_count, output_count, error_count "
        "FROM llm_extraction_runs WHERE id = $1",
        run_id,
    )
    if erun:
        print(f"  Parent run: {erun['id']}")
        print(f"  Task type:  {erun['task_type']}")
        print(f"  Status:     {erun['status']}")
        print(f"  Input:      {erun['input_count']} pairs")
        print(f"  Output:     {erun['output_count']} items")

    # Parse the extracted data
    parsed_raw = item["parsed_response_json"]
    parsed = json.loads(parsed_raw) if isinstance(parsed_raw, str) else (parsed_raw or {})
    connections = parsed.get("connections", [])
    if not connections:
        connections = parsed.get("projections", [])
    print(f"\n  Parsed connections in item: {len(connections)}")

    result["total_extracted"] = len(connections)

    # ── Step 2: Check existing mirror connections ──────────────────────────
    existing = await db.fetch(
        "SELECT id, source_region_candidate_id, target_region_candidate_id, "
        "connection_type, directionality, confidence, mirror_status, "
        "source_atlas, granularity_level, batch_id, resource_id "
        "FROM mirror_region_connections WHERE llm_item_id = $1",
        WORKFLOW_RUN_ID,
    )
    result["existing_mirror"] = len(existing)

    print(f"\n  Existing mirror_region_connections: {len(existing)}")
    if existing:
        labels = await get_candidate_labels(
            db,
            list({str(ex["source_region_candidate_id"]) for ex in existing if ex["source_region_candidate_id"]}
                 | {str(ex["target_region_candidate_id"]) for ex in existing if ex["target_region_candidate_id"]}),
        )
        for ex in existing:
            src = labels.get(str(ex["source_region_candidate_id"]), "?")
            tgt = labels.get(str(ex["target_region_candidate_id"]), "?")
            print(f"    {ex['connection_type']:30s} conf={ex['confidence']:.2f}  "
                  f"{src:20s} → {tgt:20s}  [{ex['mirror_status']}]")

    if not connections:
        print("\n[INFO] No connections found in extraction item. Nothing to recover.")
        await db.close()
        return result

    # ── Step 3: Analyze and filter connections for recovery ────────────────
    # Build existing pair set for dedup
    existing_pairs = {
        (str(ex["source_region_candidate_id"]), str(ex["target_region_candidate_id"]))
        for ex in existing
    }

    # Confidence distribution
    conf_dist: dict[str, int] = {}
    for item_conn in connections:
        c_val = item_conn.get("confidence", 0) or 0
        bucket = f"{c_val:.1f}"
        conf_dist[bucket] = conf_dist.get(bucket, 0) + 1
    print(f"\n  Confidence distribution ({len(connections)} total):")
    for bucket in sorted(conf_dist.keys()):
        print(f"    conf={bucket}: {conf_dist[bucket]}")

    # Evidence level distribution
    ev_dist: dict[str, int] = {}
    for item_conn in connections:
        ev = item_conn.get("evidence_level", "unknown") or "unknown"
        ev_dist[ev] = ev_dist.get(ev, 0) + 1
    print(f"\n  Evidence level distribution:")
    for ev in sorted(ev_dist.keys()):
        print(f"    {ev}: {ev_dist[ev]}")

    # Filter: connections with confidence >= MIN_CONFIDENCE and NOT already in mirror
    low_quality = 0
    to_insert = []
    for item_conn in connections:
        src = item_conn.get("source_candidate_id", "")
        tgt = item_conn.get("target_candidate_id", "")
        pair_key = (str(src), str(tgt))
        if pair_key in existing_pairs:
            continue
        conf_val = item_conn.get("confidence", 0) or 0
        if conf_val >= MIN_CONFIDENCE:
            to_insert.append(item_conn)
        else:
            low_quality += 1

    result["low_quality_skipped"] = low_quality

    print(f"\n  Existing in mirror:           {len(existing)}")
    print(f"  Low quality (conf < {MIN_CONFIDENCE}):   {low_quality}")
    print(f"  To recover (conf >= {MIN_CONFIDENCE}):  {len(to_insert)}")

    if not to_insert:
        print(f"\n[OK] No connections to recover above confidence {MIN_CONFIDENCE}.")
        print("     Existing 9 connections are visible in Data Center Mirror KG.")
        await db.close()
        return result

    # ── Step 4: Preview ────────────────────────────────────────────────────
    all_ids = list({str(c.get("source_candidate_id", "")) for c in to_insert}
                   | {str(c.get("target_candidate_id", "")) for c in to_insert})
    labels_all = await get_candidate_labels(db, all_ids)

    ins_conf_summary: dict[str, int] = {}
    for c in to_insert:
        bucket = f"{c.get('confidence', 0) or 0:.1f}"
        ins_conf_summary[bucket] = ins_conf_summary.get(bucket, 0) + 1
    print(f"\n  Recovery by confidence:")
    for bucket in sorted(ins_conf_summary.keys()):
        print(f"    conf={bucket}: {ins_conf_summary[bucket]}")

    print(f"\n  Sample ({min(10, len(to_insert))} of {len(to_insert)}):")
    for c in to_insert[:10]:
        src_id = str(c.get("source_candidate_id", ""))
        tgt_id = str(c.get("target_candidate_id", ""))
        src_name = labels_all.get(src_id, src_id[:8])
        tgt_name = labels_all.get(tgt_id, tgt_id[:8])
        print(f"    {c.get('connection_type','?'):30s} conf={c.get('confidence',0):.2f}  "
              f"{src_name:20s} → {tgt_name:20s}  [{c.get('evidence_level','?')}]")

    if dry_run:
        print(f"\n[DRY RUN] Would recover {len(to_insert)} connections to mirror_region_connections.")
        print("          Use --apply to execute.")
        await db.close()
        return result

    # ── Step 5: Apply recovery ─────────────────────────────────────────────
    print(f"\n[APPLY] Writing {len(to_insert)} connections...")

    template = existing[0] if existing else None
    batch_id = str(template["batch_id"]) if template and template["batch_id"] else None
    resource_id = str(template["resource_id"]) if template and template["resource_id"] else None
    source_atlas = template["source_atlas"] if template else "Macro96"
    granularity_level = template["granularity_level"] if template else "macro"

    inserted = 0
    skipped = 0
    failed = 0

    for item_conn in to_insert:
        try:
            src = str(item_conn.get("source_candidate_id", ""))
            tgt = str(item_conn.get("target_candidate_id", ""))
            ctype = item_conn.get("connection_type", "structural_connection")
            direction = item_conn.get("directionality", "undirected")
            confidence = item_conn.get("confidence", 0.1) or 0.1

            # Dedup
            check = await db.fetchrow(
                "SELECT id FROM mirror_region_connections "
                "WHERE source_region_candidate_id = $1::uuid "
                "AND target_region_candidate_id = $2::uuid "
                "AND connection_type = $3 "
                "AND directionality = $4 "
                "LIMIT 1",
                src, tgt, ctype, direction,
            )
            if check:
                skipped += 1
                continue

            attrs = {
                "composite_workflow_run_id": WORKFLOW_RUN_ID,
                "source_trace": f"recovered:{WORKFLOW_RUN_ID}",
                "recovered_at": datetime.now(timezone.utc).isoformat(),
            }
            raw_payload = dict(item_conn)
            raw_payload["attributes"] = attrs
            norm_payload = {
                "connection_type": ctype,
                "directionality": direction,
                "confidence": confidence,
                "evidence_text": item_conn.get("evidence_text", ""),
                "attributes": attrs,
            }

            await db.execute(
                "INSERT INTO mirror_region_connections "
                "(source_region_candidate_id, target_region_candidate_id, "
                "resource_id, batch_id, llm_run_id, llm_item_id, "
                "granularity_level, source_atlas, "
                "connection_type, directionality, strength, modality, "
                "confidence, evidence_text, mirror_status, review_status, "
                "raw_payload_json, normalized_payload_json) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)",
                src, tgt,
                resource_id, batch_id,
                run_id, WORKFLOW_RUN_ID,
                granularity_level, source_atlas,
                ctype, direction,
                item_conn.get("strength"), item_conn.get("modality"),
                confidence, item_conn.get("evidence_text", ""),
                "llm_suggested", "pending",
                json.dumps(raw_payload, ensure_ascii=False),
                json.dumps(norm_payload, ensure_ascii=False),
            )
            # Note: attributes (composite_workflow_run_id etc.) are embedded in
            # raw_payload_json and normalized_payload_json above.
            inserted += 1
        except Exception as e:
            failed += 1
            result["errors"].append(str(e)[:200])

    result["recovered"] = inserted
    result["skipped_existing"] = skipped
    result["failed"] = failed

    print(f"  Inserted:    {inserted}")
    print(f"  Skipped:     {skipped} (already exist)")
    print(f"  Failed:      {failed}")
    if result["errors"]:
        for e in result["errors"][:5]:
            print(f"    Error: {e}")

    await db.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="Recover connection data for extraction item")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview what would be recovered (default)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write recovered connections to mirror")
    args = parser.parse_args()

    dry_run = not args.apply
    result = asyncio.run(run(dry_run=dry_run))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Source table:        {result['source_table']}")
    print(f"  Extracted by LLM:    {result['total_extracted']}")
    print(f"  Existing in mirror:  {result['existing_mirror']}")
    print(f"  Low quality skipped: {result['low_quality_skipped']}")
    print(f"  Recovered:           {result['recovered']}")
    print(f"  Skipped (duplicate): {result['skipped_existing']}")
    print(f"  Failed:              {result['failed']}")
    print(f"  Wrote to:            mirror_region_connections")
    print(f"  Wrote final_*:       NO")
    print(f"  Wrote kg_*:          NO")
    print(f"  Auto-promoted:       NO")

    return 0


if __name__ == "__main__":
    sys.exit(main())
