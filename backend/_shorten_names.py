"""DeepSeek shorten verbose step names."""
import asyncio, sys, json, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROMPT = """Shorten these verbose step names to 2-5 words. Use concise anatomical terms.
Example: "multisensory input to left thalamus proper" -> "Left thalamus input"
Example: "convergence to right insula integration output" -> "Right insula output"
Example: "Convergence onto R17" -> "Convergence to R17"

Steps:
{steps}

Return ONLY a JSON array of strings: ["short1", "short2", ...]"""

async def main():
    from app.database import AsyncSessionLocal
    from app.services.llm_providers import get_llm_provider
    from app.services.settings_service import get_deepseek_runtime_config
    from sqlalchemy import text

    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT id::text, step_name FROM mirror_circuit_steps WHERE length(step_name) > 40 ORDER BY step_name"
        ))).fetchall()
        print(f"Verbose: {len(rows)}")

        fixed = 0
        for start in range(0, len(rows), 30):
            batch = rows[start:start+30]
            lines = "\n".join(f"{i+1}. {r[1]}" for i, r in enumerate(batch))
            try:
                resp = await provider.complete_text(
                    model=cfg.default_model, temperature=0.1, max_tokens=2000,
                    system_prompt="Output ONLY a JSON array of strings.",
                    user_prompt=PROMPT.replace("{steps}", lines),
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
                    for i, nn in enumerate(parsed):
                        if i < len(batch) and isinstance(nn, str) and len(nn) < len(batch[i][1]):
                            await s.execute(text(
                                "UPDATE mirror_circuit_steps SET step_name=:nn WHERE id=CAST(:sid AS uuid)"
                            ), {"nn": nn[:80], "sid": batch[i][0]})
                            fixed += 1
                await s.commit()
                print(f"  batch {start//30+1}: fixed={fixed}", flush=True)
            except Exception as e:
                print(f"  ERR: {e}", flush=True)
        print(f"DONE: {fixed} shortened", flush=True)

asyncio.run(main())
