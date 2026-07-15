"""DeepSeek comprehensive data quality pass — fix step names + complete functions."""
import asyncio, sys, json, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Prompts ──────────────────────────────────────────────────────────────────

FIX_NAME_PROMPT = """You are a neuroanatomist. Given a circuit name and a step description that may contain UUIDs or IDs instead of brain region names, rewrite the step name using proper anatomical terminology.
Use the circuit's context and the available candidate brain regions to infer what brain region each ID/UUID refers to.

Circuit: {circuit_name}
Candidates ({n_cands}): {candidates}
Step: {step_name}
Previous/next steps for context: {context}

Return ONLY a JSON object: {{"step_name":"<rewritten name>","confidence":0.8}}"""

FILL_FUNC_PROMPT = """You are a neuroscientist. Complete missing fields for brain circuit functions.
For each function, fill in missing values based on the function name and circuit context.

Circuit: {circuit_name} (type: {circuit_type}, desc: {desc})
Functions to complete:
{functions_list}

Fields to fill (only if currently empty): function_term_cn (Chinese name), function_domain (cognitive|memory|motor|sensory|emotional|autonomic|other), function_role (execution|modulation|inhibition|gating|integration|other), effect_type (excitatory|inhibitory|modulatory|unknown), description (1 sentence)

Return ONLY a JSON array: [{{"function_term_en":"<exact match>","function_term_cn":"...","function_domain":"...","function_role":"...","effect_type":"...","description":"..."}}, ...]"""

async def main():
    from app.database import AsyncSessionLocal
    from app.services.llm_providers import get_llm_provider
    from app.services.settings_service import get_deepseek_runtime_config
    from sqlalchemy import text

    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")

    async with AsyncSessionLocal() as s:
        # ── Candidate lookup ────────────────────────────────────────────────
        all_cands = (await s.execute(text(
            "SELECT id::text, en_name, granularity_level FROM candidate_brain_regions ORDER BY granularity_level, en_name"
        ))).fetchall()
        cands_by_gran = {}
        for cid, name, gran in all_cands:
            cands_by_gran.setdefault(gran, {})[cid.lower()] = name
            cands_by_gran.setdefault(gran, {})[cid[:12].lower()] = name
            cands_by_gran.setdefault(gran, {})[cid[:8].lower()] = name

        # ── Phase 1: Fix UUID step names ────────────────────────────────────
        SKIP_PHASE_1 = True  # Already completed (20 fixed by DeepSeek)
        if not SKIP_PHASE_1:
            print("=== PHASE 1: Fix UUID step names ===")
        uuid_re = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)
        short_re = re.compile(r'\b[0-9a-f]{8,12}\b', re.IGNORECASE)

        bad_steps = (await s.execute(text("""
            SELECT s.id::text, s.step_name, s.circuit_id::text, c.circuit_name, c.granularity_level,
                   COALESCE(prev.step_name,'') || ' | ' || COALESCE(next.step_name,'') as context
            FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id = s.circuit_id
            LEFT JOIN LATERAL (SELECT step_name FROM mirror_circuit_steps p WHERE p.circuit_id=s.circuit_id AND p.step_order<s.step_order ORDER BY p.step_order DESC LIMIT 1) prev ON true
            LEFT JOIN LATERAL (SELECT step_name FROM mirror_circuit_steps n WHERE n.circuit_id=s.circuit_id AND n.step_order>s.step_order ORDER BY n.step_order LIMIT 1) next ON true
            WHERE s.step_name ~ '[0-9a-f]{8}-[0-9a-f]{4}|[0-9a-f]{8,}'
            ORDER BY c.granularity_level, c.circuit_name
        """))).fetchall()
        print(f"Bad step names: {len(bad_steps)}")

        fixed = 0
        for batch_num, start in enumerate(range(0, len(bad_steps), 10)):
            batch = bad_steps[start:start+10]
            # Try deterministic fix first
            for sid, sname, cid, cname, gran, ctx in batch:
                new_name = sname
                gran_cands = cands_by_gran.get(gran, {})
                for match in uuid_re.findall(sname):
                    rname = gran_cands.get(match.lower())
                    if not rname: rname = gran_cands.get(match[:12].lower()) or gran_cands.get(match[:8].lower())
                    if rname: new_name = new_name.replace(match, rname)
                if new_name == sname:
                    for match in short_re.findall(sname):
                        if len(match) < 8: continue
                        rname = gran_cands.get(match.lower())
                        if rname: new_name = new_name.replace(match, rname)
                if new_name != sname:
                    await s.execute(text("UPDATE mirror_circuit_steps SET step_name=:nn WHERE id=CAST(:sid AS uuid)"), {"nn": new_name, "sid": sid})
                    fixed += 1
            await s.commit()
            print(f"  deterministic batch {batch_num+1}: fixed={fixed}", flush=True)

        # Remaining: use DeepSeek
        still_bad = (await s.execute(text("""
            SELECT s.id::text, s.step_name, c.circuit_name, c.granularity_level,
                   COALESCE(prev.step_name,'') || ' | ' || COALESCE(next.step_name,'') as context
            FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id = s.circuit_id
            LEFT JOIN LATERAL (SELECT step_name FROM mirror_circuit_steps p WHERE p.circuit_id=s.circuit_id AND p.step_order<s.step_order ORDER BY p.step_order DESC LIMIT 1) prev ON true
            LEFT JOIN LATERAL (SELECT step_name FROM mirror_circuit_steps n WHERE n.circuit_id=s.circuit_id AND n.step_order>s.step_order ORDER BY n.step_order LIMIT 1) next ON true
            WHERE s.step_name ~ '[0-9a-f]{8}-[0-9a-f]{4}|[0-9a-f]{8,}'
        """))).fetchall()
        print(f"Still bad after deterministic: {len(still_bad)}")

        for batch_num, start in enumerate(range(0, len(still_bad), 10)):
            batch = still_bad[start:start+10]
            if not batch: break
            parts = []
            for sid, sname, cname, gran, ctx in batch:
                gran_cands = cands_by_gran.get(gran, {})
                cand_list = "\n".join(f"  - {v}" for v in list(set(gran_cands.values()))[:50])
                parts.append(FIX_NAME_PROMPT.format(circuit_name=cname, n_cands=len(set(gran_cands.values())), candidates=cand_list, step_name=sname, context=ctx))
            combined = "\n---\n".join(parts)

            try:
                resp = await provider.complete_text(
                    model=cfg.default_model, temperature=0.1, max_tokens=4000,
                    system_prompt="Output ONLY a JSON array of objects. No markdown.",
                    user_prompt=f"Fix these step names. Return a JSON array with one object per step:\n{combined}\n\nJSON array:",
                )
                raw = (resp.raw_text or '').strip()
                if raw.startswith('```'): raw = '\n'.join(l for l in raw.split('\n') if not l.startswith('```'))
                try: parsed = json.loads(raw)
                except:
                    m = re.search(r'\[.*\]', raw, re.DOTALL)
                    parsed = json.loads(m.group(0)) if m else []
                if isinstance(parsed, list):
                    for i, item in enumerate(parsed):
                        if i < len(batch) and isinstance(item, dict) and item.get("step_name"):
                            sid = batch[i][0]
                            await s.execute(text("UPDATE mirror_circuit_steps SET step_name=:nn WHERE id=CAST(:sid AS uuid)"), {"nn": item["step_name"], "sid": sid})
                            fixed += 1
                await s.commit()
                print(f"  DeepSeek batch {batch_num+1}: total_fixed={fixed}", flush=True)
            except Exception as e:
                print(f"  ERROR batch {batch_num+1}: {e}", flush=True)

        print(f"\nPhase 1 done: {fixed} step names fixed", flush=True)

        # ── Phase 2: Complete circuit functions ─────────────────────────────
        print("\n=== PHASE 2: Complete circuit functions ===")
        funcs_need = (await s.execute(text("""
            SELECT f.id::text, f.function_term_en, f.function_domain, f.function_role, f.effect_type, f.description,
                   c.circuit_name, c.circuit_type, c.description as circuit_desc, c.granularity_level
            FROM mirror_circuit_functions f
            JOIN mirror_region_circuits c ON c.id = f.circuit_id
            WHERE (f.description IS NULL OR f.effect_type IS NULL OR f.function_term_cn IS NULL OR f.function_role IS NULL)
            ORDER BY c.granularity_level, c.circuit_name
        """))).fetchall()
        print(f"Functions needing completion: {len(funcs_need)}")

        func_filled = 0
        # Group by circuit for efficient batching
        by_circuit = {}
        for row in funcs_need:
            ckey = (row[6], row[7], row[8] or "", row[9])
            by_circuit.setdefault(ckey, []).append(row)

        for batch_num, (ckey, funcs) in enumerate(by_circuit.items()):
            cname, ctype, cdesc, gran = ckey
            func_list = "\n".join(f"  - {row[1]} (domain:{row[2] or '?'} role:{row[3] or '?'} effect:{row[4] or '?'})" for row in funcs[:20])
            if not func_list.strip(): continue

            try:
                resp = await provider.complete_text(
                    model=cfg.default_model, temperature=0.15, max_tokens=8000,
                    system_prompt="Output ONLY a JSON array. No markdown.",
                    user_prompt=FILL_FUNC_PROMPT.format(circuit_name=cname, circuit_type=ctype, desc=cdesc, functions_list=func_list),
                )
                raw = (resp.raw_text or '').strip()
                if raw.startswith('```'): raw = '\n'.join(l for l in raw.split('\n') if not l.startswith('```'))
                try: parsed = json.loads(raw)
                except:
                    m = re.search(r'\[.*\]', raw, re.DOTALL)
                    parsed = json.loads(m.group(0)) if m else []
                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict): continue
                        fen = item.get("function_term_en", "").strip()
                        updates = []
                        params = {}
                        for field in ("function_term_cn","function_domain","function_role","effect_type","description"):
                            val = item.get(field)
                            if val and str(val).strip():
                                updates.append(f"{field}=:{field}")
                                params[field] = str(val).strip()
                        params["fen"] = fen
                        if updates:
                            await s.execute(text(f"UPDATE mirror_circuit_functions SET {','.join(updates)} WHERE circuit_id IN (SELECT id FROM mirror_region_circuits WHERE circuit_name=:cname) AND function_term_en=:fen"), {"cname": cname, **params})
                            func_filled += 1
                await s.commit()
                if (batch_num + 1) % 10 == 0:
                    print(f"  circuit batch {batch_num+1}/{len(by_circuit)}: func_filled~{func_filled}", flush=True)
            except Exception as e:
                print(f"  ERROR circuit {cname[:30]}: {e}", flush=True)

        print(f"\nPhase 2 done: {func_filled} functions completed", flush=True)

        # ── Final stats ────────────────────────────────────────────────────
        async with AsyncSessionLocal() as fs:
            still_bad_names = (await fs.execute(text("""
                SELECT count(*) FROM mirror_circuit_steps s
                JOIN mirror_region_circuits c ON c.id=s.circuit_id
                WHERE s.step_name ~ '[0-9a-f]{8}-[0-9a-f]{4}|[0-9a-f]{8,}'
            """))).scalar_one()
            null_region = (await fs.execute(text("""
                SELECT count(*) FROM mirror_circuit_steps s
                JOIN mirror_region_circuits c ON c.id=s.circuit_id
                WHERE s.region_candidate_id IS NULL
            """))).scalar_one()
            null_func_fields = (await fs.execute(text("""
                SELECT count(*) FROM mirror_circuit_functions WHERE description IS NULL OR effect_type IS NULL
            """))).scalar_one()
            print(f"\nFINAL: bad_names={still_bad_names} null_regions={null_region} null_func_fields={null_func_fields}", flush=True)

asyncio.run(main())
