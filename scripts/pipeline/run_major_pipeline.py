from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.pipeline.major_workflow import run_major_load, run_major_preview
from scripts.utils.io_utils import ensure_dir, write_json
from scripts.utils.runtime import build_common_parser, resolve_run_id


def run_major_pipeline(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    resolved_run_id = resolve_run_id(run_id)
    root = ensure_dir(output_path) / resolved_run_id
    preview_summary = run_major_preview(
        input_path=input_path,
        output_path=root,
        config_path=config_path,
        run_id=resolved_run_id,
    )
    load_summary = run_major_load(
        preview_root=root,
        config_path=config_path,
        run_id=f"{resolved_run_id}_load",
    )
    summary = {
        "run_id": resolved_run_id,
        "status": "success",
        "preview": preview_summary,
        "load": load_summary,
        "paths": {"root": str(root)},
    }
    write_json(root / "major_pipeline_summary.json", summary)
    return summary


def main() -> None:
    parser = build_common_parser("Run anatomy + major DeepSeek pipeline (preview then load).")
    args = parser.parse_args()
    summary = run_major_pipeline(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"major_pipeline done: {summary['status']} ({summary['run_id']})")


if __name__ == "__main__":
    main()

