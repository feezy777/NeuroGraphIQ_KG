"""DeepSeek match remaining steps to candidate brain regions by step name context."""
import asyncio, sys, json, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROMPT = """Match these circuit step descriptions to the candidate brain regions below.
Each step name contains brain region hints (e.g. "Sensory input left thalamus" -> left thalamus proper).

Candidates:
{candidates}

Circuit: {circuit_name}
Steps:
{steps}

Return ONLY a JSON array: [{{"step_name":"<exact>","region":"<candidate region name>","confidence":0.8}}, ...]
Use confidence=0.1 if uncertain. region="none" if truly unmatchable."""

async def main():
    from app.database import AsyncSessionLocal
    from app.services.llm_providers import get_llm_provider
    from app.services.settings_service import get_deepseek_runtime_config
    from sqlalchemy import text

    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")

    async with AsyncSessionLocal() as s:
        cands = (await s.execute(text(
            "SELECT id::text, en_name FROM candidate_brain_regions WHERE granularity_level='macro' ORDER BY en_name"
        ))).fetchall()
        cand_map = {row[1].lower(): row[0] for row in cands}
        cand_list = "\n".join(f"  - {row[1]}" for row in cands)

        # Get circuits with NULL-region steps
        rows = (await s.execute(text("""
            SELECT s.id::text, s.step_name, c.circuit_name, c.id::text
            FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id = s.circuit_id
            WHERE c.granularity_level='macro' AND s.region_candidate_id IS NULL
            ORDER BY c.circuit_name
        """))).fetchall()
        print(f"Steps needing region: {len(rows)}")

        fixed = 0
        for start in range(0, len(rows), 20):
            batch = rows[start:start+20]
            lines = "\n".join(f"  - {r[1]}" for r in batch)
            cname = batch[0][2] if batch else "?"
            try:
                resp = await provider.complete_text(
                    model=cfg.default_model, temperature=0.1, max_tokens=3000,
                    system_prompt="Output ONLY a JSON array. No markdown.",
                    user_prompt=PROMPT.format(candidates=cand_list, circuit_name=cname, steps=lines),
                )
                raw = (resp.raw_text or "").strip()
                if raw.startswith("```"):
                    raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```"))
                try: parsed = json.loads(raw)
                except:
                    m = re.search(r"\[.*\]", raw, re.DOTALL)
                    parsed = json.loads(m.group(0)) if m else []
                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict): continue
                        sn = item.get("step_name", "").strip()
                        rn = (item.get("region") or "").strip().lower()
                        if rn and rn != "none":
                            cid = cand_map.get(rn)
                            if not cid:
                                for k, v in cand_map.items():
                                    if rn in k or k in rn:
                                        cid = v; break
                            if cid:
                                await s.execute(text(
                                    "UPDATE mirror_circuit_steps SET region_candidate_id=CAST(:rid AS uuid) WHERE step_name=:sn AND region_candidate_id IS NULL"
                                ), {"rid": cid, "sn": sn})
                                fixed += 1
                await s.commit()
                print(f"  batch {start//20+1}: fixed={fixed}", flush=True)
            except Exception as e:
                print(f"  ERR: {e}", flush=True)

        # Final stats
        still = (await s.execute(text("""
            SELECT count(*) FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id=s.circuit_id
            WHERE c.granularity_level='macro' AND s.region_candidate_id IS NULL
        """))).scalar_one()
        print(f"Remaining NULL: {still}", flush=True)

asyncio.run(main())
