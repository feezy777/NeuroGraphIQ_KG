"""Clean up bad circuit names: UUID fragments, aliases (R1/r1), 'unknown', Chinese."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import asyncio, selectors
from app.database import AsyncSessionLocal
from sqlalchemy import text

async def cleanup():
    async with AsyncSessionLocal() as s:
        # Find all circuits
        r = await s.execute(text("SELECT id, circuit_name FROM mirror_region_circuits"))
        rows = list(r)
        bad_ids = []
        for rid, name in rows:
            name_lower = name.lower()
            # Check for UUID fragments (8+ consecutive hex chars)
            import re
            if re.search(r'[0-9a-f]{8,}', name_lower):
                bad_ids.append(rid)
                continue
            # Check for aliases like R1, r2
            if re.search(r'(?:^|_)[rR]\d+(?:$|_)', name):
                bad_ids.append(rid)
                continue
            # Check for "unknown"
            if 'unknown' in name_lower:
                bad_ids.append(rid)
                continue
            # Check for Chinese characters
            if any('一' <= c <= '鿿' for c in name):
                bad_ids.append(rid)
                continue

        print(f"Bad circuits: {len(bad_ids)} out of {len(rows)}")
        if bad_ids:
            # Show bad names
            for rid, name in rows:
                if rid in bad_ids:
                    print(f"  DEL: {name[:80]}")
        if not bad_ids:
            for rid, name in rows[:10]:
                print(f"  OK: {name[:80]}")
            return

        # Delete cascade
        placeholders = ','.join(f"'{id}'" for id in bad_ids)
        await s.execute(text(f"DELETE FROM mirror_circuit_functions WHERE circuit_id IN ({placeholders})"))
        await s.execute(text(f"DELETE FROM mirror_circuit_steps WHERE circuit_id IN ({placeholders})"))
        await s.execute(text(f"DELETE FROM mirror_region_circuits WHERE id IN ({placeholders})"))
        await s.commit()
        print(f"Deleted {len(bad_ids)} bad circuits + steps/functions")

if __name__ == '__main__':
    asyncio.run(cleanup(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
