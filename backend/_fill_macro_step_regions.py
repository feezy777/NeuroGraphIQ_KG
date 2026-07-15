"""Match macro circuit_name to candidate regions, assign to steps."""
import asyncio, sys, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    from app.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as s:
        # Get circuits with NULL-region steps, with their names
        circuits = (await s.execute(text("""
            SELECT c.id::text, c.circuit_name, array_agg(s.id::text ORDER BY s.step_order) as step_ids
            FROM mirror_region_circuits c
            JOIN mirror_circuit_steps s ON s.circuit_id = c.id AND s.region_candidate_id IS NULL
            WHERE c.granularity_level = 'macro'
            GROUP BY c.id
        """))).fetchall()
        print(f"Circuits needing region match: {len(circuits)}")

        # Candidate regions with their names
        cands = (await s.execute(text(
            "SELECT id::text, lower(trim(en_name)) FROM candidate_brain_regions WHERE granularity_level='macro'"
        ))).fetchall()
        cand_map = {cid: name for cid, name in cands}
        print(f"Candidates: {len(cands)}")

        # For each circuit, find matching regions from circuit_name
        matched = 0
        for cid, cname, step_ids in circuits:
            if not cname: continue
            name = cname.lower().replace('_', ' ').replace('-', ' ')

            # Token-based matching: find 2+ word phrases that match candidate names
            tokens = [t for t in re.split(r'[\s,;/]+', name) if len(t) > 2]
            found = []
            # Try phrase matching (2-3 token combinations)
            for i in range(len(tokens)):
                for j in range(i+1, min(i+4, len(tokens))):
                    phrase = ' '.join(tokens[i:j+1])
                    if len(phrase) < 5: continue
                    for cand_id, cand_name in cands:
                        if phrase in cand_name and cand_id not in found:
                            found.append(cand_id)
                            break
                    if len(found) >= len(step_ids):
                        break
                if len(found) >= len(step_ids):
                    break

            # Fallback: single-word matching
            if len(found) < len(step_ids):
                for tok in tokens:
                    if len(tok) < 4 or tok in ('left','right','the','and','circuit','pathway','network','motor','sensory','from','to','for'):
                        continue
                    for cand_id, cand_name in cands:
                        if tok in cand_name and cand_id not in found:
                            found.append(cand_id)
                            break
                    if len(found) >= len(step_ids):
                        break

            # Assign to steps in order
            for i, step_id in enumerate(step_ids):
                if i < len(found):
                    await s.execute(text(
                        "UPDATE mirror_circuit_steps SET region_candidate_id=CAST(:rid AS uuid) WHERE id=CAST(:sid AS uuid)"
                    ), {"rid": found[i], "sid": step_id})
                    matched += 1

        await s.commit()
        print(f"Matched: {matched} steps across {len(circuits)} circuits")
        still_null = (await s.execute(text("""
            SELECT count(*) FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id=s.circuit_id
            WHERE c.granularity_level='macro' AND s.region_candidate_id IS NULL
        """))).scalar_one()
        print(f"Still NULL: {still_null}")

asyncio.run(main())
