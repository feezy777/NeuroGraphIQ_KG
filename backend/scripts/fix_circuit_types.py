"""Fix circuit_type values from raw LLM output using the alias map.

One-shot script — reads raw_payload_json->>'circuit_type' for circuits where
circuit_type='unknown', maps via CIRCUIT_TYPE_ALIAS_MAP, and updates in place.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Comprehensive alias map matching llm_circuit_extraction_service.py + observed LLM outputs.
# Maps LLM-friendly names → DB-check-constraint-approved CircuitType enum values.
ALIAS_MAP: dict[str, str] = {
    # --- Legacy prompt names (from llm_circuit_extraction_service.py) ---
    "sensory_pathway": "sensory_circuit",
    "motor_pathway": "motor_circuit",
    "associative_pathway": "cognitive_control_circuit",
    "cognitive_circuit": "cognitive_control_circuit",
    "language_circuit": "language_related",
    "default_mode_circuit": "default_mode_related",
    "salience_circuit": "salience_related",
    "attention_circuit": "attention_related",
    "thalamocortical_loop": "sensory_circuit",
    "basal_ganglia_loop": "motor_circuit",
    "cerebellar_loop": "motor_circuit",
    "brainstem_circuit": "uncertain_circuit",
    "memory_circuit": "memory_related",
    "emotion_circuit": "limbic_circuit",
    "visual_circuit": "sensory_circuit",
    "auditory_circuit": "sensory_circuit",
    "somatosensory_circuit": "sensory_circuit",
    "multisensory_integration": "uncertain_circuit",
    "other": "unknown",
    # --- Short forms observed in actual raw_payload_json ---
    "motor": "motor_circuit",
    "language": "language_related",
    "visual": "sensory_circuit",
    "cognitive": "cognitive_control_circuit",
    "attention": "attention_related",
    "reward": "reward_related",
    "memory": "memory_related",
    "limbic": "limbic_circuit",
    "cerebellar": "motor_circuit",
    "sensorimotor": "sensory_circuit",
    "oculomotor": "motor_circuit",
    "thalamocortical": "sensory_circuit",
    "subcortical": "uncertain_circuit",
    "structural": "unknown",
    "arousal": "uncertain_circuit",
    # --- Compound / multi-word forms ---
    "cognitive_control": "cognitive_control_circuit",
    "memory_emotion": "limbic_circuit",
    "emotion_related": "limbic_circuit",
    "emotion_interoception": "limbic_circuit",
    "emotion_memory": "limbic_circuit",
    "reward_emotion": "reward_related",
    "motor_control": "motor_circuit",
    "motor_related": "motor_circuit",
    "sensory_related": "sensory_circuit",
    "visual_processing": "sensory_circuit",
    "visual_attention": "attention_related",
    "visual_object": "sensory_circuit",
    "auditory_language": "language_related",
    "somatosensory_spatial": "sensory_circuit",
    "default_mode": "default_mode_related",
    "default_mode_network": "default_mode_related",
    "executive_control": "cognitive_control_circuit",
    "thalamo-striatal": "motor_circuit",
    "cerebello-thalamic": "motor_circuit",
    "anatomical_ventricular": "unknown",
    "anatomical_white_matter": "unknown",
    "memory_default_mode": "memory_related",
}


async def main():
    # Reconstruct from components (asyncpg uses postgresql:// not postgresql+psycopg_async)
    dsn = (
        f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '')}@"
        f"{os.getenv('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'neurographiq_kg_v3_mvp1_e2e')}"
    )

    conn = await asyncpg.connect(dsn)

    # Count circuits needing fix
    total = await conn.fetchval(
        "SELECT count(*) FROM mirror_region_circuits WHERE circuit_type = 'unknown'"
    )
    print(f"Circuits with unknown type: {total}")

    # Read all and categorize by raw type
    rows = await conn.fetch(
        """SELECT id, circuit_name, raw_payload_json
           FROM mirror_region_circuits
           WHERE circuit_type = 'unknown'"""
    )

    fixed = 0
    skipped = 0
    stats: dict[str, int] = {}

    for row in rows:
        raw = row["raw_payload_json"] or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue
        if not isinstance(raw, dict):
            skipped += 1
            continue
        raw_type = raw.get("circuit_type", "")
        if not raw_type:
            skipped += 1
            continue

        new_type = ALIAS_MAP.get(raw_type.lower(), raw_type.lower())
        stats[raw_type] = stats.get(raw_type, 0) + 1

        try:
            await conn.execute(
                "UPDATE mirror_region_circuits SET circuit_type = $1 WHERE id = $2",
                new_type, row["id"],
            )
            fixed += 1
        except Exception:
            # Fallback: use uncertain_circuit for anything that fails the check constraint
            await conn.execute(
                "UPDATE mirror_region_circuits SET circuit_type = $1 WHERE id = $2",
                "uncertain_circuit", row["id"],
            )
            fixed += 1
            stats[f"{raw_type}→uncertain"] = stats.get(f"{raw_type}→uncertain", 0) + 1

        if fixed % 500 == 0:
            print(f"  Fixed {fixed} / {total}...")

    await conn.close()
    print(f"\nDone: fixed={fixed}, skipped={skipped}")
    print(f"Stats by original LLM type:")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v} → {ALIAS_MAP.get(k, '?')}")


if __name__ == "__main__":
    asyncio.run(main())
