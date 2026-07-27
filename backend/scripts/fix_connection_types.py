"""Use DeepSeek to re-evaluate connection_type and directionality for all molecular connections."""
import json, sys, time, logging, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.services.llm_providers.factory import get_llm_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(msg)s")
logger = logging.getLogger(__name__)
API = "http://127.0.0.1:8003"
BATCH = 20  # connections per LLM call

SYSTEM = """You are a neuroanatomy expert. For each brain region connection pair below, determine:
1. connection_type: "structural_connection" (direct anatomical fiber pathway), "association" (within same region/area), "projection" (long-range), or "functional_connectivity" (correlated activity, no known direct fiber)
2. directionality: "directed" (one-way), "undirected" (bidirectional or unknown)

Rules:
- Cortical layers within same region → "association", "undirected"
- Long-range cortico-cortical → "projection", "directed"
- Cerebellar-cortical connections → "projection", "directed"
- Subcortical-cortical connections → "projection", "directed"
- If uncertain, use "structural_connection" and "undirected"

Output ONLY valid JSON array: [{"id":"conn_uuid","connection_type":"...","directionality":"..."}]"""


def build_prompt(batch):
    lines = ["Analyze these brain region connection pairs:"]
    for i, c in enumerate(batch):
        lines.append(f"{i+1}. ID={c['id']} | {c['src']} -> {c['tgt']}")
    return "\n".join(lines)


def call_llm(prompt, settings, provider):
    import asyncio
    async def _call():
        for attempt in range(2):
            try:
                resp = await provider.complete_text(
                    model="deepseek-chat", system_prompt=SYSTEM, user_prompt=prompt,
                    temperature=0.1, max_tokens=4000, timeout_seconds=60, json_mode=True,
                )
                if resp.transport_ok and resp.raw_text:
                    return resp.raw_text.strip()
            except Exception as e:
                logger.warning(f"LLM attempt {attempt+1}: {e}")
                if attempt == 0: await asyncio.sleep(3)
        return None
    return asyncio.run(_call())


def main():
    # Fetch all molecular connections
    logger.info("Fetching molecular connections...")
    all_conns = []
    offset = 0
    while True:
        url = f"{API}/api/mirror-kg/connections?granularity_level=molecular_attr&limit=5000&offset={offset}"
        resp = json.loads(urllib.request.urlopen(url, timeout=120).read().decode())
        items = resp["items"]
        if not items: break
        all_conns.extend(items)
        offset += len(items)
        logger.info(f"  Fetched {len(all_conns)}...")
    logger.info(f"Total: {len(all_conns)} connections")

    # Batch them
    batches = [all_conns[i:i+BATCH] for i in range(0, len(all_conns), BATCH)]
    logger.info(f"Batches: {len(batches)}")

    settings = get_settings()
    provider = get_llm_provider("deepseek")
    updated = 0
    start = time.time()

    for bi, batch in enumerate(batches):
        # Build prompt with connection names
        conn_data = [{"id": c["id"], "src": c.get("source_region_name_en", "?"), "tgt": c.get("target_region_name_en", "?")} for c in batch]
        prompt = build_prompt(conn_data)
        raw = call_llm(prompt, settings, provider)

        if not raw:
            logger.warning(f"Batch {bi+1}: empty response")
            continue

        if raw.startswith("```"): raw = raw.split("\n", 1)[1]
        if raw.endswith("```"): raw = raw[:-3]

        try: parsed = json.loads(raw)
        except: logger.warning(f"Batch {bi+1}: parse error"); continue

        if isinstance(parsed, dict) and "_array" in parsed: parsed = parsed["_array"]
        if not isinstance(parsed, list): continue

        # Update each connection via API
        for item in parsed:
            cid = item.get("id", "")
            ctype = item.get("connection_type", "")
            direction = item.get("directionality", "")
            if not cid or not ctype: continue

            body = json.dumps({"connection_type": ctype, "directionality": direction}).encode()
            try:
                req = urllib.request.Request(f"{API}/api/mirror-kg/connections/{cid}",
                    data=body, headers={"Content-Type": "application/json"}, method="PATCH")
                urllib.request.urlopen(req, timeout=10)
                updated += 1
            except Exception as e:
                pass  # skip failures silently

        elapsed = time.time() - start
        rate = (bi+1) / max(elapsed, 1) * 60
        eta = (len(batches) - bi - 1) / max(rate, 0.1) * 60
        logger.info(f"Batch {bi+1}/{len(batches)} ({100*(bi+1)//len(batches)}%) updated={updated} rate={rate:.0f}/m ETA={eta/3600:.1f}h")

    logger.info(f"DONE! Updated {updated} connections")


if __name__ == "__main__":
    main()
