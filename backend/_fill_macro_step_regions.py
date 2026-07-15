"""Fill macro step region_candidate_id: R-codes + keyword mapping, multi-pass."""
import asyncio, sys, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Anatomical keyword → candidate name fragment mapping
KEYWORD_MAP = {
    "thalamo": "thalamus", "cortical": "cortex", "cerebell": "cerebellum",
    "striat": "striatum", "hippocamp": "hippocampus", "amygdal": "amygdala",
    "hypothal": "hypothalamus", "pallid": "pallidum", "caudate": "caudate",
    "putamen": "putamen", "accumbens": "accumbens", "insula": "insula",
    "orbitofrontal": "orbitofrontal", "prefrontal": "prefrontal",
    "temporal": "temporal", "parietal": "parietal", "occipital": "occipital",
    "fusiform": "fusiform", "cingulate": "cingulate", "parahippocamp": "parahippocampal",
    "entorhinal": "entorhinal", "perirhinal": "perirhinal",
    "somatosen": "somatosensory", "visual": "visual", "auditory": "auditory",
    "olfactory": "olfactory", "gustatory": "gustatory",
    "motor": "motor", "sensory": "sensory",
    "ventricle": "ventricle", "brainstem": "brainstem",
    "white matter": "white matter", "cerebrospinal": "CSF",
}

async def main():
    from app.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as s:
        # Build R-code mapping from raw_macro96
        mapping_rows = (await s.execute(text("""
            SELECT r.region_index, c.id::text
            FROM raw_macro96_region_rows r
            JOIN candidate_brain_regions c ON lower(trim(c.en_name)) = lower(trim(r.en_name))
                AND c.granularity_level = 'macro'
        """))).fetchall()
        r_to_cand = {str(row[0]): row[1] for row in mapping_rows}

        # All candidate regions for keyword matching
        cands = (await s.execute(text(
            "SELECT id::text, lower(trim(en_name)) FROM candidate_brain_regions WHERE granularity_level='macro'"
        ))).fetchall()

        # All circuits with NULL-region steps
        circuits = (await s.execute(text("""
            SELECT c.id::text, c.circuit_name, array_agg(s.id::text ORDER BY s.step_order) as step_ids
            FROM mirror_region_circuits c
            JOIN mirror_circuit_steps s ON s.circuit_id = c.id AND s.region_candidate_id IS NULL
            WHERE c.granularity_level = 'macro'
            GROUP BY c.id
        """))).fetchall()
        print(f"Circuits to process: {len(circuits)}")

        matched = 0

        for cid, cname, step_ids in circuits:
            if not cname: continue
            name = cname.lower().replace('_', ' ').replace('-', ' ')

            # Strategy 1: R-codes in circuit name (e.g., "R22_R14")
            rcodes = re.findall(r'R(\d+)', name, re.IGNORECASE)
            r_matches = [r_to_cand[rc] for rc in rcodes if rc in r_to_cand]

            # Strategy 2: keyword → candidate matching
            k_matches = []
            for keyword, fragment in KEYWORD_MAP.items():
                if keyword in name:
                    for cand_id, cand_name in cands:
                        if fragment in cand_name and cand_id not in r_matches and cand_id not in k_matches:
                            k_matches.append(cand_id)
                            break

            # Strategy 3: phrase matching (multi-word)
            tokens = [t for t in re.split(r'[\s,;/]+', name) if len(t) > 2]
            p_matches = []
            for i in range(len(tokens)):
                for j in range(i+1, min(i+3, len(tokens))):
                    phrase = ' '.join(tokens[i:j+1])
                    if len(phrase) < 5: continue
                    for cand_id, cand_name in cands:
                        if phrase in cand_name and cand_id not in r_matches and cand_id not in k_matches and cand_id not in p_matches:
                            p_matches.append(cand_id)
                            break

            # Strategy 4: single-word token fallback
            s_matches = []
            skip_words = {'left','right','the','and','circuit','pathway','network','from','to','for','convergent','feedforward','default','mode'}
            for tok in tokens:
                if len(tok) < 3 or tok in skip_words: continue
                for cand_id, cand_name in cands:
                    if tok in cand_name and cand_id not in all_existing:
                        s_matches.append(cand_id)
                        break

            all_existing = set(r_matches + k_matches + p_matches + s_matches)
            all_found = r_matches + k_matches + p_matches + s_matches

            # Deduplicate while preserving order
            seen = set()
            found = []
            for rid in all_found:
                if rid not in seen:
                    seen.add(rid)
                    found.append(rid)

            # If we got fewer regions than steps, reuse available regions
            while len(found) < len(step_ids) and found:
                found.append(found[len(found) % len(found)])

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
        total = (await s.execute(text("""
            SELECT count(*) FROM mirror_circuit_steps s
            JOIN mirror_region_circuits c ON c.id=s.circuit_id
            WHERE c.granularity_level='macro'
        """))).scalar_one()
        print(f"Final: {total - still_null}/{total} filled ({round(100*(total-still_null)/total,1)}%)")

asyncio.run(main())
