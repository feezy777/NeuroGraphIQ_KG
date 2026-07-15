"""Field completion on all macro projections — connection type verification + strength fill."""
import asyncio, sys, uuid
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    from app.database import AsyncSessionLocal
    from app.schemas.llm_field_completion import (
        UniversalFieldCompletionRequest, TargetType, FieldScope, OverwritePolicy,
    )
    from app.services import llm_field_completion_service as svc
    from app.models.llm_field_completion import LlmFieldCompletionRun
    from sqlalchemy import select, text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT id FROM mirror_region_connections WHERE granularity_level='macro' ORDER BY source_region_name_en"
        ))).fetchall()
    all_ids = [r[0] for r in rows]
    print(f"Total macro projections: {len(all_ids)}", flush=True)

    batch_size = 200
    for batch_num, start in enumerate(range(0, len(all_ids), batch_size)):
        batch = all_ids[start:start + batch_size]
        end_idx = min(start + batch_size, len(all_ids))
        print(f"\n=== BATCH {batch_num + 1} ({start + 1}-{end_idx} of {len(all_ids)}) ===", flush=True)

        body = UniversalFieldCompletionRequest(
            provider="deepseek", target_type=TargetType.projection,
            target_ids=batch,
            field_scope=FieldScope.missing_only, dry_run=False,
            create_mirror_updates=True, overwrite_policy=OverwritePolicy.fill_missing_only,
        )
        async with AsyncSessionLocal() as s:
            start_resp = await svc.start_field_completion_async(s, body)
        run_id = start_resp.run_id
        print(f"  RUN: {run_id}", flush=True)
        await svc.execute_field_completion_background(run_id, body.model_dump(mode="json"))

        async with AsyncSessionLocal() as s:
            run = await s.get(LlmFieldCompletionRun, run_id)
            summary = run.summary_json or {}
            print(f"  STATUS: {run.status}  "
                  f"applied={summary.get('applied_overlay_count','?')}  "
                  f"llm_applied={summary.get('llm_applied_count','?')}  "
                  f"calls={summary.get('model_call_count','?')}  "
                  f"errors={run.errors_json or '[]'}", flush=True)

    print("\nDONE — All macro projection batches complete", flush=True)

asyncio.run(main())
