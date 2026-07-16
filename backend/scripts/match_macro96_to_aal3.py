"""Phase 1: Match 96 Macro96 regions to AAL3 atlas labels via DeepSeek.

Reads data/macro96_regions.json + data/aal3_labels.json,
calls DeepSeek to match by name, and writes results to
data/macro96_aal3_match_results.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm_providers.factory import get_llm_provider
from app.config import get_settings


PROMPT = """You are a neuroanatomy expert. I have two lists:

**List A: Macro96 Brain Regions** (96 custom regions from a clinical brain volume list)
**List B: AAL3 Atlas Labels** (166 standard AAL3 v1 regions)

Your task:
1. For EACH of the 96 Macro96 regions, find the BEST matching AAL3 label (or mark as unmatched)
2. For each match, provide the standard MNI152 centroid coordinate (x, y, z in mm) for that AAL3 region
3. Classify each match quality as: exact, alias_matched, approximate, manual_review, or unmapped

Matching rules:
- Match by neuroanatomical name, not string similarity alone
- Validate laterality: left brain regions must match left AAL3 labels, right→right, midline→midline
- "white matter", "CSF", "ventricle", "cerebellum" are structural/global labels — may match multiple AAL3 subregions or be unmapped
- "brain stem" maps to AAL3 brainstem structures (Midbrain, Pons, Medulla)
- Composite names like "left frontal lobe" should match the closest AAL3 cortical region
- Do NOT invent coordinates — use only standard AAL3 MNI152 centroids
- If uncertain, mark as manual_review with reason

Return ONLY valid JSON in this exact format:
```json
{
  "matches": [
    {
      "macro96_id": 1,
      "macro96_name_en": "left frontal lobe",
      "macro96_name_cn": "左额叶",
      "macro96_laterality": "left",
      "aal3_index": 3,
      "aal3_name": "Frontal_Sup_2_L",
      "match_quality": "exact",
      "mni_centroid": {"x": -24.5, "y": 32.1, "z": 45.2},
      "confidence": 0.95,
      "rationale": "Macro96 'left frontal lobe' best matches AAL3 #3 Frontal_Sup_2_L by anatomical hierarchy"
    }
  ],
  "unmatched": [
    {
      "macro96_id": 1,
      "macro96_name_en": "white matter",
      "reason": "Global white matter label — no single AAL3 region corresponds. Would need WM parcellation atlas."
    }
  ],
  "summary": {
    "total_macro96": 96,
    "total_matched": 85,
    "total_unmatched": 11,
    "exact_matches": 60,
    "alias_matches": 15,
    "approximate_matches": 5,
    "manual_review": 5
  }
}
```"""


def build_match_prompt(macro96: list[dict], aal3_labels: list[dict]) -> str:
    """Build the matching prompt with both lists."""
    lines = [PROMPT, "", "=== LIST A: Macro96 Brain Regions ==="]
    for r in macro96:
        lines.append(
            f"#{r['label_value']}: en={r['name_en']} | cn={r['name_cn']} | lat={r['laterality']}"
        )
    lines.append("")
    lines.append("=== LIST B: AAL3 Atlas Labels ===")
    for a in aal3_labels:
        lines.append(f"#{a['index']}: {a['name']} | hemi={a['hemisphere']}")
    lines.append("")
    lines.append("Now output ONLY the JSON (no markdown, no extra text):")
    return "\n".join(lines)


async def main():
    settings = get_settings()
    api_key = settings.deepseek_api_key
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY not set in .env")
        sys.exit(1)

    # Load data
    data_dir = Path(__file__).resolve().parents[1] / "data"
    with open(data_dir / "macro96_regions.json", encoding="utf-8") as f:
        macro96 = json.load(f)
    with open(data_dir / "aal3_labels.json", encoding="utf-8") as f:
        aal3_labels = json.load(f)

    print(f"Loaded {len(macro96)} Macro96 regions + {len(aal3_labels)} AAL3 labels")

    # Build prompt
    user_prompt = build_match_prompt(macro96, aal3_labels)
    print(f"Prompt size: {len(user_prompt)} chars")

    # Call DeepSeek
    provider = get_llm_provider("deepseek")
    model = settings.deepseek_default_model or "deepseek-chat"

    print(f"Calling DeepSeek model={model}...")
    result = await provider.complete_text(
        model=model,
        system_prompt="You are a neuroanatomy expert specializing in brain atlas mapping. Output only valid JSON, no markdown fences, no extra text.",
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=32000,
        timeout_seconds=180,
        json_mode=True,
    )

    if not result.transport_ok or not result.raw_text:
        print(f"ERROR: Provider call failed: {result.error}")
        sys.exit(1)

    # Parse response
    raw = result.raw_text.strip()
    # Remove markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Raw response (first 500 chars): {raw[:500]}")
        # Save raw for debugging
        with open(data_dir / "macro96_aal3_raw_response.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"Saved raw response to data/macro96_aal3_raw_response.txt")
        sys.exit(1)

    # Validate
    matches = parsed.get("matches", [])
    unmatched = parsed.get("unmatched", [])
    summary = parsed.get("summary", {})
    print(f"Results: {len(matches)} matched, {len(unmatched)} unmatched")
    if summary:
        print(f"Summary: {json.dumps(summary, ensure_ascii=False)}")

    # Save results
    output_path = data_dir / "macro96_aal3_match_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    print(f"Saved to {output_path}")

    # Print match statistics
    quality_counts = {}
    for m in matches:
        q = m.get("match_quality", "unknown")
        quality_counts[q] = quality_counts.get(q, 0) + 1
    print(f"By quality: {json.dumps(quality_counts, ensure_ascii=False)}")

    # Print unmatched
    if unmatched:
        print(f"\n=== UNMATCHED ({len(unmatched)}) ===")
        for u in unmatched:
            print(f"  #{u['macro96_id']}: {u['macro96_name_en']} — {u['reason']}")


if __name__ == "__main__":
    asyncio.run(main())
