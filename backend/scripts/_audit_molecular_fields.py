"""One-shot audit of molecular circuit field coverage / FK constraints."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from app.database import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT conname, pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = 'mirror_region_circuits'::regclass
                      AND contype = 'f'
                    """
                )
            )
        ).all()
        print("=== FKs on mirror_region_circuits ===")
        for r in rows:
            print(r[0], "=>", r[1])

        n = (
            await s.execute(
                text(
                    """
                    SELECT count(*) FROM mirror_region_circuits
                    WHERE granularity_level='molecular_attr'
                      AND mirror_status NOT IN (
                        'llm_suggested','rule_checked','human_review_pending',
                        'human_approved','human_rejected','promoted_to_final','superseded'
                      )
                    """
                )
            )
        ).scalar()
        print("invalid_status_count", n)

        for label, sql in [
            ("total", "select count(*) from mirror_region_circuits where granularity_level='molecular_attr'"),
            ("with_evidence", "select count(*) from mirror_region_circuits where granularity_level='molecular_attr' and evidence_text is not null and evidence_text<>''"),
            ("with_family", "select count(*) from mirror_region_circuits where granularity_level='molecular_attr' and granularity_family is not null"),
            ("with_llm_run", "select count(*) from mirror_region_circuits where granularity_level='molecular_attr' and llm_run_id is not null"),
            ("with_raw", "select count(*) from mirror_region_circuits where granularity_level='molecular_attr' and raw_payload_json::text not in ('{}','null')"),
            (
                "circuit_region_rows",
                """
                select count(*) from mirror_circuit_regions mcr
                join mirror_region_circuits c on c.id=mcr.circuit_id
                where c.granularity_level='molecular_attr'
                """,
            ),
        ]:
            print(label, (await s.execute(text(sql))).scalar())


if __name__ == "__main__":
    asyncio.run(main())
