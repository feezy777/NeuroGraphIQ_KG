"""Extract ONLY new molecular pairs using DeepSeek API + mirror API writes."""
import json, sys, time, uuid, logging, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.llm_providers.factory import get_llm_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(msg)s")
logger = logging.getLogger(__name__)
PAIRS_PER_PACK = 60
API = "http://127.0.0.1:8003"

SYSTEM_PROMPT = """You are a neuroanatomy expert. Given pairs of brain regions, identify known structural connections. For each pair with a connection, output: source_region_candidate_id, target_region_candidate_id, connection_type (structural_connection/association/projection), directionality (directed/undirected), confidence (0-1), evidence (description). For pairs WITHOUT connection, output no_connection with reason. Output ONLY valid JSON: {"connections":[...], "no_connections":[...]}"""


def build_prompt(pack, candidates):
    cmap = {c["id"]: c for c in candidates}
    lines = ["Analyze these brain region pairs for connections:\n"]
    for i, p in enumerate(pack):
        sc = cmap.get(p["source_region_candidate_id"], {})
        tc = cmap.get(p["target_region_candidate_id"], {})
        lines.append(f"{i+1}. {sc.get('en_name','?')} | {tc.get('en_name','?')} (pair={p['source_region_candidate_id'][:8]}..{p['target_region_candidate_id'][:8]})")
    return "\n".join(lines)


def call_deepseek(system, user, settings, provider):
    import asyncio
    async def _call():
        for attempt in range(2):
            try:
                resp = await provider.complete_text(
                    model=settings.deepseek_default_model or "deepseek-chat",
                    system_prompt=system, user_prompt=user,
                    temperature=0.3, max_tokens=12000, timeout_seconds=180, json_mode=True,
                )
                if resp.transport_ok and resp.raw_text:
                    return resp.raw_text.strip()
            except Exception as e:
                logger.warning(f"  LLM attempt {attempt+1}: {e}")
                if attempt == 0: await asyncio.sleep(5)
        return None
    return asyncio.run(_call())


def post_api(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{API}{path}", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    # Load data
    with open("data/new_molecular_pairs.json") as f:
        pairs = json.load(f)["pairs"]
    packs = [pairs[i:i+PAIRS_PER_PACK] for i in range(0, len(pairs), PAIRS_PER_PACK)]
    logger.info(f"New pairs: {len(pairs)} | Packs: {len(packs)} | Est: {len(packs)*45/3600:.1f}h")

    resp = json.loads(urllib.request.urlopen(f"{API}/api/candidates/brain-regions?granularity_level=molecular_attr&limit=600").read().decode())
    candidates = resp["items"]
    logger.info(f"Candidates: {len(candidates)}")

    settings = get_settings()
    provider = get_llm_provider("deepseek")

    total_c, total_s, total_f = 0, 0, 0
    start = time.time()

    for i, pack in enumerate(packs):
        user = build_prompt(pack, candidates)
        raw = call_deepseek(SYSTEM_PROMPT, user, settings, provider)

        if not raw:
            total_f += 1; logger.error(f"Pack {i+1}: empty"); continue

        if raw.startswith("```"): raw = raw.split("\n", 1)[1]
        if raw.endswith("```"): raw = raw[:-3]

        try:
            parsed = json.loads(raw)
        except:
            total_f += 1; logger.warning(f"Pack {i+1}: parse error"); continue

        conns = parsed.get("connections", [])
        if isinstance(conns, dict):
            conns = list(conns.values()) if "_array" not in conns else conns["_array"]

        c, s = 0, 0
        for conn in conns:
            sid = conn.get("source_region_candidate_id", "")
            tid = conn.get("target_region_candidate_id", "")
            if not sid or not tid: continue

            # Find candidate info
            sc = next((x for x in candidates if x["id"] == sid), {})
            tc = next((x for x in candidates if x["id"] == tid), {})

            body = {
                "source_region_candidate_id": sid,
                "target_region_candidate_id": tid,
                "source_region_name_en": sc.get("en_name", "") or "",
                "target_region_name_en": tc.get("en_name", "") or "",
                "source_region_name_cn": sc.get("cn_name", "") or "",
                "target_region_name_cn": tc.get("cn_name", "") or "",
                "connection_type": conn.get("connection_type", "structural_connection"),
                "directionality": conn.get("directionality", "undirected"),
                "confidence": float(conn.get("confidence", 0.5)),
                "evidence_text": conn.get("evidence", "") or "",
                "granularity_level": "molecular_attr",
                "granularity_family": "molecular_attr",
                "source_atlas": sc.get("source_atlas", "Allen_HBA_2012") or "Allen_HBA_2012",
            }
            try:
                r = post_api("/api/mirror-kg/connections", body)
                if r.get("id"):
                    c += 1
                else:
                    s += 1  # duplicate
            except Exception as e:
                logger.warning(f"  Write error: {e}")

        total_c += c
        total_s += s
        elapsed = time.time() - start
        rate = (i + 1) / max(elapsed, 1) * 60
        eta = (len(packs) - i - 1) / max(rate, 0.01) * 60
        logger.info(f"P{i+1}/{len(packs)}({100*(i+1)//len(packs)}%) new={c} dup={s} total={total_c} rate={rate:.1f}/m ETA={eta/3600:.1f}h")

    logger.info(f"DONE! Created={total_c} Skipped={total_s} Failed={total_f}")
    tc = json.loads(urllib.request.urlopen(f"{API}/api/mirror-kg/connections?granularity_level=molecular_attr&limit=1").read().decode())
    logger.info(f"Total connections: {tc['total']}")


if __name__ == "__main__":
    main()
