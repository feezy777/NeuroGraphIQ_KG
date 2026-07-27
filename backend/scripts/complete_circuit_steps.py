"""Use DeepSeek to generate circuit steps for circuits that have 0 steps.
Batched with per-circuit commit.
"""
import asyncio, sys, json, logging, uuid, re, selectors
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.mirror_kg import MirrorRegionCircuit, MirrorCircuitRegion
from app.models.mirror_macro_clinical import MirrorCircuitStep
from app.config import get_settings
from app.services.llm_providers.factory import get_llm_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(msg)s")
logger = logging.getLogger(__name__)
BATCH = 3  # circuits per LLM call

SYSTEM = """You are a neuroanatomy expert. Given a brain circuit, generate its sequential steps. Each step includes: step_order (1-based), step_name (English, snake_case), step_type (region|connection), role (source|relay|integrator|target|participant), region_id (the candidate region UUID from the circuit's member regions), confidence (0-1), description (brief). Output ONLY JSON array."""


async def main():
    settings = get_settings()
    provider = get_llm_provider("deepseek")
    model = "deepseek-chat"

    async with AsyncSessionLocal() as session:
        # Get circuits with 0 steps
        total = await session.scalar(select(func.count()).select_from(MirrorRegionCircuit).where(
            MirrorRegionCircuit.granularity_level == 'molecular_attr'
        ))
        logger.info(f"Total molecular circuits: {total}")

        # Get circuits needing steps
        q = select(MirrorRegionCircuit).where(
            MirrorRegionCircuit.granularity_level == 'molecular_attr'
        ).order_by(MirrorRegionCircuit.created_at.asc()).limit(100)  # oldest first
        result = await session.execute(q)
        circuits = list(result.scalars().all())
        logger.info(f"Test batch: {len(circuits)} circuits")

        for c in circuits:
            # Get member regions
            mr = await session.execute(select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == c.id))
            members = mr.scalars().all()

            # Count existing steps
            sc = await session.scalar(select(func.count()).select_from(MirrorCircuitStep).where(MirrorCircuitStep.circuit_id == c.id))
            if sc > 0:
                logger.info(f"  SKIP {c.circuit_name[:40]}: already has {sc} steps")
                continue

            # Build prompt
            region_list = "\n".join(f"  - {m.region_candidate_id} (role={m.role or 'participant'})" for m in members)
            prompt = f"""Circuit: {c.circuit_name}
Type: {c.circuit_type or 'unknown'}
Description: {c.description or 'N/A'}
Function: {c.function_association or 'N/A'}
Member regions:
{region_list}

Generate 2-5 sequential steps for this circuit. Output JSON array:
[{{"step_order":1,"step_name":"...","step_type":"region","role":"source","region_id":"<UUID from list above>","confidence":0.7,"description":"..."}}]"""

            logger.info(f"  Processing: {c.circuit_name[:50]}")

            # Call LLM
            for attempt in range(2):
                try:
                    resp = await provider.complete_text(
                        model=model, system_prompt=SYSTEM, user_prompt=prompt,
                        temperature=0.3, max_tokens=2000, timeout_seconds=60, json_mode=True,
                    )
                    if resp.transport_ok and resp.raw_text:
                        raw = resp.raw_text.strip()
                        if raw.startswith("```"): raw = raw.split("\n", 1)[1]
                        if raw.endswith("```"): raw = raw[:-3]
                        steps = json.loads(raw)
                        if isinstance(steps, dict) and "_array" in steps:
                            steps = steps["_array"]
                        if not isinstance(steps, list):
                            logger.warning(f"    Not a list")
                            continue

                        created = 0
                        for sdata in steps:
                            rid_str = sdata.get("region_id", "")
                            try: rid = uuid.UUID(rid_str)
                            except: continue
                            step = MirrorCircuitStep(
                                circuit_id=c.id,
                                step_order=int(sdata.get("step_order", created+1)),
                                step_name=str(sdata.get("step_name", f"step_{created+1}"))[:256],
                                step_type=str(sdata.get("step_type", "region"))[:64],
                                role=str(sdata.get("role", "participant"))[:64],
                                region_candidate_id=rid,
                                confidence=float(sdata.get("confidence", 0.5)),
                                description=str(sdata.get("description", ""))[:1024],
                                granularity_level=c.granularity_level or "molecular_attr",
                            )
                            session.add(step)
                            created += 1
                        await session.commit()
                        logger.info(f"    Created {created} steps")
                        break
                except Exception as e:
                    logger.warning(f"    Attempt {attempt+1} failed: {e}")
                    if attempt == 1:
                        logger.error(f"    FAILED: {c.circuit_name[:40]}")


if __name__ == "__main__":
    asyncio.run(main())
