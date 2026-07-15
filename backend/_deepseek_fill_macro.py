"""DeepSeek batch: fill macro step regions + roles, with confidence scores."""
import asyncio, sys, json, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

STEP_PROMPT = """You are a neuroanatomist. Given a brain circuit name and a list of candidate brain regions (from the Macro96 atlas), identify which region each step belongs to. Also assign a role to each step.

Candidate regions ({count} total):
{candidates}

Circuit: {circuit_name}
Steps to annotate:
{steps_list}

Return a JSON array. One object per step. Include confidence (0.0-1.0) for each match.
[{{"step_name":"...",  "region":"<exact candidate region name>", "role":"source|relay|target|hub|modulator|participant", "confidence":0.8}}, ...]

For uncertain matches, use lower confidence. If a step genuinely cannot be matched, use region:"unknown" with confidence:0.1.
ONLY use candidate regions from the list above. Reply ONLY the JSON array, no markdown, no explanation."""

ROLE_PROMPT = """Annotate the role of each step in this brain circuit. Roles: source (starting point), relay (intermediate), target (endpoint), hub (integration point), modulator (modulates/influences), participant (general involvement).

Circuit: {circuit_name} (type: {circuit_type})
Steps:
{steps_list}

Return ONLY a JSON array: [{{"step_name":"...", "role":"source"}}, ...]. No markdown, no explanation."""

async def main():
    from app.database import AsyncSessionLocal
    from app.services.llm_providers import get_llm_provider
    from app.services.settings_service import get_deepseek_runtime_config
    from sqlalchemy import text

    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")

    async with AsyncSessionLocal() as s:
        # ── All 96 candidate regions ────────────────────────────────────────
        cands = (await s.execute(text(
            "SELECT id::text, en_name FROM candidate_brain_regions WHERE granularity_level='macro' ORDER BY en_name"
        ))).fetchall()
        cand_map = {row[1]: row[0] for row in cands}
        cand_list = "\n".join(f"  - {row[1]}" for row in cands)

        # ── Circuits needing step region fill ────────────────────────────────
        circuits = (await s.execute(text("""
            SELECT c.id::text, c.circuit_name, c.circuit_type,
                   array_agg(json_build_object('id',s.id::text,'name',s.step_name,'order',s.step_order) ORDER BY s.step_order) as steps
            FROM mirror_region_circuits c
            JOIN mirror_circuit_steps s ON s.circuit_id = c.id AND s.region_candidate_id IS NULL
            WHERE c.granularity_level = 'macro'
            GROUP BY c.id
        """))).fetchall()
        print(f"Circuits needing region fill: {len(circuits)}")

        region_filled = 0
        role_filled = 0
        total_calls = 0

        for batch_num, start in enumerate(range(0, len(circuits), 5)):
            batch = circuits[start:start+5]
            batch_text = []
            for cid, cname, ctype, steps_json in batch:
                steps = json.loads(steps_json) if isinstance(steps_json, str) else steps_json
                steps_list = "\n".join(f"  {s['order']}. {s['name']}" for s in steps)
                batch_text.append(f"Circuit: {cname}\n{steps_list}")

            combined = "\n---\n".join(batch_text)
            print(f"\nBatch {batch_num+1}: {len(batch)} circuits, {sum(len(json.loads(s[3]) if isinstance(s[3],str) else s[3]) for s in batch)} steps", flush=True)

            try:
                resp = await provider.complete_text(
                    model=cfg.default_model,
                    system_prompt="You are a neuroanatomist. Output ONLY a JSON array. No markdown, no explanation.",
                    user_prompt=STEP_PROMPT.format(
                        count=len(cands), candidates=cand_list,
                        circuit_name="Multiple circuits (see below)", steps_list=combined,
                    ),
                    temperature=0.1, max_tokens=8000,
                )
                total_calls += 1
                raw = (resp.raw_text or '').strip()
                if raw.startswith('```'): raw = '\n'.join(l for l in raw.split('\n') if not l.startswith('```'))
                try: parsed = json.loads(raw)
                except:
                    m = re.search(r'\[.*\]', raw, re.DOTALL)
                    parsed = json.loads(m.group(0)) if m else None
                if not isinstance(parsed, list):
                    print(f"  WARN: not a list, type={type(parsed).__name__}", flush=True)
                    continue

                # Write matches back
                async with AsyncSessionLocal() as ws:
                    for item in parsed:
                        if not isinstance(item, dict): continue
                        sn = item.get("step_name", "").strip()
                        region_name = item.get("region", "").strip()
                        role = item.get("role", "").strip()
                        conf = float(item.get("confidence", 0.5))
                        if region_name and region_name != "unknown" and region_name in cand_map:
                            cid_region = cand_map[region_name]
                            # Update region + confidence in normalized_payload
                            await ws.execute(text("""
                                UPDATE mirror_circuit_steps SET region_candidate_id=CAST(:rid AS uuid),
                                normalized_payload_json = COALESCE(normalized_payload_json,'{}'::jsonb) || jsonb_build_object('confidence',CAST(:conf AS text))
                                WHERE step_name=:sn AND region_candidate_id IS NULL
                            """), {"rid": cid_region, "sn": sn, "conf": str(conf)})
                            region_filled += 1
                        if role and role not in ('unknown',''):
                            await ws.execute(text("""
                                UPDATE mirror_circuit_steps SET role=:role, normalized_payload_json = COALESCE(normalized_payload_json,'{}'::jsonb) || jsonb_build_object('role_source','deepseek')
                                WHERE step_name=:sn AND (role='unknown' OR role IS NULL)
                            """), {"role": role, "sn": sn})
                            role_filled += 1
                    await ws.commit()
                print(f"  region_filled={region_filled} role_filled={role_filled}", flush=True)
            except Exception as e:
                print(f"  ERROR: {e}", flush=True)

        print(f"\nFINAL: {total_calls} LLM calls, {region_filled} regions, {role_filled} roles", flush=True)

asyncio.run(main())
