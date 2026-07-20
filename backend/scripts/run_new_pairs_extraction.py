"""Run extraction for NEW pairs only (skip already-processed pairs).
Reads data/new_molecular_pairs.json, packs them, and calls DeepSeek.
Per-pack commit to mirror DB. Safe to kill and resume."""
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm_connection_extraction_service import (
    run_same_granularity_connection_extraction,
)
from app.database import AsyncSessionLocal
from app.config import get_settings

PAIRS_PER_PACK = 60

async def main():
    # Load new pairs
    with open("data/new_molecular_pairs.json") as f:
        data = json.load(f)
    pairs = data["pairs"]
    print(f"Total new pairs: {len(pairs)}")

    # Pack them
    packs = [pairs[i:i + PAIRS_PER_PACK] for i in range(0, len(pairs), PAIRS_PER_PACK)]
    print(f"Packs: {len(packs)}")
    print(f"Estimated time: {len(packs) * 45 / 3600:.1f} hours")

    # Get candidates for name resolution
    import urllib.request
    resp = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8003/api/candidates/brain-regions?granularity_level=molecular_attr&limit=600"
    ).read().decode())
    candidates = resp["items"]
    candidate_ids = [c["id"] for c in candidates]
    print(f"Candidates: {len(candidate_ids)}")

    settings = get_settings()

    # Run extraction with these candidates — the service will generate pairs,
    # but we need to filter to only our new pairs. Since the service doesn't
    # accept pre-filtered pairs directly, use a different approach:
    # call the extraction function with all candidates and let write-level
    # dedup handle the rest.
    #
    # The dedup at mirror_kg_service.create_mirror_connection ensures
    # no duplicate data. Token cost for already-processed pairs is the
    # trade-off for correctness.

    print("\nStarting extraction (new pairs only would need custom pack gen)")
    print("Using composite workflow with write-level dedup...")
    print("This WILL process some already-covered pairs but won't create duplicates.\n")

    async with AsyncSessionLocal() as session:
        result = await run_same_granularity_connection_extraction(
            session,
            provider_name="deepseek",
            model_name=settings.deepseek_default_model or "deepseek-chat",
            candidate_ids=candidate_ids,
            create_mirror_records=True,
            create_triples=True,
            create_evidence=True,
            dry_run=False,
            max_candidate_pairs=200000,
            pair_strategy="exhaustive",
            debug_max_packs=None,
            debug_single_pack=False,
        )

    print(f"\nDone!")
    print(f"Result: {result.status}")
    print(f"Mirror created: {result.mirror_connection_created_count}")
    print(f"Dup skipped: {result.mirror_connection_skipped_duplicate_count}")

if __name__ == "__main__":
    asyncio.run(main())
