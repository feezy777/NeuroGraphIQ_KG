from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.extract.llm_extract_circuits import run_extract_circuits
from scripts.utils.io_utils import read_json


def test_extract_circuits_reports_seed_traversal(tmp_path: Path) -> None:
    regions_path = tmp_path / "regions.jsonl"
    regions = [
        {"major_region_id": "REG_MAJOR_FRONTAL_CORTEX_LEFT", "en_name": "frontal cortex", "cn_name": "额叶皮层", "laterality": "left"},
        {"major_region_id": "REG_MAJOR_THALAMUS_PROPER_LEFT", "en_name": "thalamus proper", "cn_name": "丘脑本体", "laterality": "left"},
        {"major_region_id": "REG_MAJOR_UNKNOWN_MIDLINE", "en_name": "unknown region", "cn_name": "未知区域", "laterality": "midline"},
    ]
    regions_path.write_text(
        "\n".join([json.dumps(row, ensure_ascii=False) for row in regions]),
        encoding="utf-8",
    )

    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "llm": {"use_deepseek": False},
                "pipeline": {"major_circuit_target_count": 50, "major_circuit_seed_instance_cap": 3, "major_circuit_hard_cap": 200},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "major_circuits.raw.jsonl"
    report = run_extract_circuits(
        input_path=regions_path,
        output_path=output_path,
        config_path=str(config_path),
        run_id="run_test_seed",
    )

    assert report["seed_region_count"] == 3
    assert report["attempted_region_count"] == 3
    assert report["attempted_region_count"] == report["seed_region_count"]
    assert report["uncovered_region_count"] >= 1
    assert "REG_MAJOR_UNKNOWN_MIDLINE" in report["uncovered_regions"]
    assert Path(report["seed_traversal_path"]).exists()
    assert Path(report["uncovered_regions_path"]).exists()

    uncovered = read_json(report["uncovered_regions_path"])
    assert "REG_MAJOR_UNKNOWN_MIDLINE" in uncovered.get("uncovered_regions", [])
