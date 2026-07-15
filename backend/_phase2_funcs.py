"""DeepSeek Phase 2: complete circuit function fields."""
import asyncio, sys, json, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

FILL_FUNC_PROMPT = """You are a neuroscientist. Complete missing fields for brain circuit functions.
Circuit: {circuit_name} (type: {circuit_type}, desc: {desc})
Functions to complete:
{functions_list}
Return ONLY a JSON array: [{{"function_term_en":"<exact>","function_term_cn":"...","function_domain":"...","function_role":"...","effect_type":"...","description":"..."}},...]"""

async def main():
    from app.database import AsyncSessionLocal
    from app.services.llm_providers import get_llm_provider
    from app.services.settings_service import get_deepseek_runtime_config
    from sqlalchemy import text

    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")

    async with AsyncSessionLocal() as s:
        funcs = (await s.execute(text("""
            SELECT f.id::text, f.function_term_en, f.function_domain, f.function_role, f.effect_type, f.description, f.function_term_cn,
                   c.circuit_name, c.circuit_type, coalesce(c.description,'') as cdesc
            FROM mirror_circuit_functions f
            JOIN mirror_region_circuits c ON c.id = f.circuit_id
            WHERE f.description IS NULL OR f.effect_type IS NULL OR f.function_term_cn IS NULL OR f.function_role IS NULL
            ORDER BY c.circuit_name
        """))).fetchall()
        print(f"Functions needing completion: {len(funcs)}")

        by_circuit = {}
        for row in funcs:
            ckey = (row[7], row[8], row[9] or "")
            by_circuit.setdefault(ckey, []).append(row)
        print(f"Circuits: {len(by_circuit)}")

        filled = 0
        for bi, (ckey, flist) in enumerate(by_circuit.items()):
            cname, ctype, cdesc = ckey
            lines = "\n".join(f"  - {r[1]} (domain:{r[2] or '?'} role:{r[3] or '?'} effect:{r[4] or '?'})" for r in flist[:15])
            if not lines.strip(): continue

            try:
                resp = await provider.complete_text(
                    model=cfg.default_model, temperature=0.15, max_tokens=6000,
                    system_prompt="Output ONLY a JSON array. No markdown.",
                    user_prompt=FILL_FUNC_PROMPT.format(circuit_name=cname, circuit_type=ctype, desc=cdesc, functions_list=lines),
                )
                raw = (resp.raw_text or "").strip()
                if raw.startswith("```"):
                    raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```"))
                try:
                    parsed = json.loads(raw)
                except Exception:
                    m = re.search(r"\[.*\]", raw, re.DOTALL)
                    parsed = json.loads(m.group(0)) if m else []

                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict): continue
                        fen = item.get("function_term_en", "").strip()
                        if not fen: continue
                        sets = []; params = {}
                        for fld in ("function_term_cn", "function_domain", "function_role", "effect_type", "description"):
                            v = item.get(fld)
                            if v and str(v).strip():
                                sets.append(f"{fld}=:{fld}")
                                params[fld] = str(v).strip()
                        if sets:
                            params["fen"] = fen; params["cn"] = cname
                            await s.execute(text(
                                f"UPDATE mirror_circuit_functions SET {','.join(sets)} "
                                "WHERE circuit_id IN (SELECT id FROM mirror_region_circuits WHERE circuit_name=:cn) "
                                "AND function_term_en=:fen"
                            ), params)
                            filled += 1
                await s.commit()
                if (bi + 1) % 20 == 0:
                    print(f"  circuit {bi+1}/{len(by_circuit)}: filled~{filled}", flush=True)
            except Exception as e:
                print(f"  ERR {cname[:30]}: {e}", flush=True)

        print(f"\nDONE: {filled} functions completed", flush=True)

asyncio.run(main())
