"""Replace UUIDs in macro step names with actual candidate_brain_regions.en_name."""
import asyncio, sys, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    from app.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as s:
        # Build UUID → en_name lookup from candidate_brain_regions
        cands = (await s.execute(text(
            "SELECT id::text, en_name FROM candidate_brain_regions WHERE granularity_level='macro'"
        ))).fetchall()
        id_to_name = {row[0]: row[1] for row in cands}
        # Also try short UUID prefixes (8-12 chars)
        short_map = {}
        for cid, name in id_to_name.items():
            for l in (8, 12):
                short_map[cid[:l].lower()] = name

        # Find macro steps with UUID-like names
        rows = (await s.execute(text("""
            SELECT s.id::text, s.step_name, s.circuit_id::text
            FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id = s.circuit_id
            WHERE c.granularity_level = 'macro'
              AND s.step_name ~ '[0-9a-f]{8}-[0-9a-f]{4}|[0-9a-f]{8,}'
        """))).fetchall()
        print(f"Steps with UUID patterns: {len(rows)}")

        updated = 0
        uuid_re = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)
        short_re = re.compile(r'\b[0-9a-f]{8,12}\b', re.IGNORECASE)

        for sid, name, cid in rows:
            new_name = name
            # Replace full UUIDs
            for match in uuid_re.findall(name):
                region_name = id_to_name.get(match) or id_to_name.get(match.lower())
                if not region_name:
                    region_name = short_map.get(match[:12].lower()) or short_map.get(match[:8].lower())
                if region_name:
                    new_name = new_name.replace(match, region_name)
            # Replace short UUIDs (8-12 hex chars)
            if new_name == name:
                for match in short_re.findall(name):
                    if match.isdigit() or len(match) < 8: continue
                    region_name = short_map.get(match.lower())
                    if region_name:
                        new_name = new_name.replace(match, region_name)

            if new_name != name:
                await s.execute(text("UPDATE mirror_circuit_steps SET step_name=:nn WHERE id=CAST(:sid AS uuid)"), {"nn": new_name, "sid": sid})
                updated += 1

        await s.commit()
        print(f"Updated: {updated}/{len(rows)} step names")

asyncio.run(main())
