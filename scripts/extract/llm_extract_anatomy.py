from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.constants import (
    DIV_NON_LOBE_DIVISION_BRAIN_ID,
    ORG_HUMAN_ID,
    ORGN_HUMAN_BRAIN_ID,
    SYS_NERVOUS_ID,
)
from scripts.utils.io_utils import write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def run_extract_anatomy(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = input_path
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)

    organism_id = ORG_HUMAN_ID
    system_id = SYS_NERVOUS_ID
    organ_id = ORGN_HUMAN_BRAIN_ID
    division_id = DIV_NON_LOBE_DIVISION_BRAIN_ID

    records = [
        {
            "entity_type": "organism",
            "organism_id": organism_id,
            "organism_code": organism_id,
            "en_name": "Human",
            "cn_name": "human",
            "species": "Homo sapiens",
            "data_source": "deepseek_pipeline",
            "status": "active",
            "run_id": resolved_run_id,
        },
        {
            "entity_type": "anatomical_system",
            "system_id": system_id,
            "organism_id": organism_id,
            "system_code": system_id,
            "en_name": "Nervous System",
            "cn_name": "nervous_system",
            "data_source": "deepseek_pipeline",
            "status": "active",
            "run_id": resolved_run_id,
        },
        {
            "entity_type": "organ",
            "organ_id": organ_id,
            "system_id": system_id,
            "organ_code": organ_id,
            "en_name": "Human Brain",
            "cn_name": "human_brain",
            "data_source": "deepseek_pipeline",
            "status": "active",
            "run_id": resolved_run_id,
        },
        {
            "entity_type": "brain_division",
            "division_id": division_id,
            "organ_id": organ_id,
            "division_code": division_id,
            "en_name": "Brain (Non-lobe)",
            "cn_name": "brain_non_lobe",
            "division_type": "non_lobe_division",
            "data_source": "deepseek_pipeline",
            "status": "active",
            "run_id": resolved_run_id,
        },
    ]

    output = Path(output_path)
    count = write_jsonl(output, records)
    report = {
        "stage": "extract_anatomy",
        "run_id": resolved_run_id,
        "output_records": count,
        "output_path": str(output),
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Extract fixed anatomy base entities.")
    args = parser.parse_args()
    report = run_extract_anatomy(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"extract_anatomy done: {report['output_records']}")


if __name__ == "__main__":
    main()
