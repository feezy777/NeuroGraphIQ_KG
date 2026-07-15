"""Batch-verify macro connection types + fill strength in ONE LLM call per batch."""
import asyncio, sys, json
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BATCH_SIZE = 50
PROMPT = """Review these brain connections. For EACH connection, verify the connection_type and assign a strength_score (0.0-1.0).

Valid types: structural_connection, functional_connectivity, projection, association, coactivation, effective_connectivity, uncertain_connection

IMPORTANT: You MUST return ONE JSON object PER connection. Return them ALL as a JSON array.
Example: [{"id":"abc-123","connection_type":"structural_connection","strength_score":0.7}, {"id":"def-456","connection_type":"functional_connectivity","strength_score":0.3}]

{connections}"""

async def main():
    from app.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT id, source_region_name_en, target_region_name_en, connection_type "
            "FROM mirror_region_connections WHERE granularity_level='macro' ORDER BY id"
        ))).fetchall()

    all_rows = [(str(r[0]), r[1] or '?', r[2] or '?', r[3] or 'unknown') for r in rows]
    print(f"Total: {len(all_rows)}", flush=True)

    # Config
    from app.services.llm_providers.base import LlmProviderResponse
    from app.services.llm_providers import get_llm_provider
    from app.services.settings_service import get_deepseek_runtime_config

    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")

    updated_type = 0
    updated_strength = 0
    total_calls = 0

    for batch_num, start in enumerate(range(0, len(all_rows), BATCH_SIZE)):
        batch = all_rows[start:start + BATCH_SIZE]
        lines = []
        for cid, src, tgt, ctype in batch:
            lines.append(f'{{"id":"{cid}","source":"{src}","target":"{tgt}","current_type":"{ctype}"}}')
        conn_text = "\n".join(lines)

        print(f"\nBatch {batch_num+1} ({start+1}-{min(start+BATCH_SIZE, len(all_rows))}) — sending {len(batch)} connections...", flush=True)

        try:
            resp = await provider.complete_text(
                model=cfg.default_model,
                system_prompt="You are a neuroscientist reviewing brain connections. You MUST return ONLY a JSON array — one object per connection. No markdown, no code fences, no explanation. Just the raw JSON array starting with [ and ending with ].",
                user_prompt=PROMPT.replace("{connections}", conn_text),
                temperature=0.15,
                max_tokens=16000,
            )
            total_calls += 1

            raw = (resp.raw_text or '').strip()
            # Strip markdown fences
            if raw.startswith('```'):
                lines = raw.split('\n')
                raw = '\n'.join(l for l in lines if not l.startswith('```')).strip()
            try:
                parsed = json.loads(raw)
            except Exception:
                # Try extracting array from messy response
                import re
                m = re.search(r'\[.*\]', raw, re.DOTALL)
                if m:
                    try: parsed = json.loads(m.group(0))
                    except Exception: parsed = None
                else:
                    parsed = None
            if not isinstance(parsed, list):
                # Try common wrappers
                if isinstance(parsed, dict):
                    # Single-object response: wrap in list
                    if "id" in parsed and "connection_type" in parsed:
                        parsed = [parsed]
                    else:
                        for key in ("connections", "projections", "results", "items", "_array"):
                            val = parsed.get(key)
                            if isinstance(val, list):
                                parsed = val
                                break
                        if not isinstance(parsed, list):
                            for v in parsed.values():
                                if isinstance(v, list):
                                    parsed = v
                                    break
                if not isinstance(parsed, list):
                    print(f"  SKIP: response not a list, type={type(parsed).__name__}", flush=True)
                    continue

            # Write results
            async with AsyncSessionLocal() as s:
                for item in parsed:
                    if not isinstance(item, dict): continue
                    cid = item.get("id")
                    new_type = item.get("connection_type")
                    new_strength = item.get("strength_score")
                    if not cid: continue

                    if new_type and new_type in ('structural_connection','functional_connectivity','projection','association','coactivation','effective_connectivity','uncertain_connection','unknown'):
                        await s.execute(text(
                            "UPDATE mirror_region_connections SET connection_type=:ct WHERE id=CAST(:cid AS uuid) AND connection_type IS DISTINCT FROM :ct"
                        ), {"cid": str(cid), "ct": new_type})
                        updated_type += 1

                    if new_strength is not None:
                        try:
                            val = float(new_strength)
                            val = max(0.0, min(1.0, val))
                            await s.execute(text(
                                "UPDATE mirror_region_connections SET strength=:st WHERE id=CAST(:cid AS uuid) AND strength IS NULL"
                            ), {"cid": str(cid), "st": str(val)})
                            updated_strength += 1
                        except (TypeError, ValueError): pass

                await s.commit()

            print(f"  done — type_updates={updated_type} strength_fills={updated_strength}", flush=True)

        except Exception as e:
            import traceback
            print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()

    print(f"\nFINAL: {len(all_rows)} connections, {total_calls} LLM calls, {updated_type} types changed, {updated_strength} strength filled", flush=True)

asyncio.run(main())
