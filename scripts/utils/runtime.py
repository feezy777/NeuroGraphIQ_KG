from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from scripts.utils.config_loader import load_yaml


def build_common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--input", required=True, help="Input file or directory path.")
    parser.add_argument("--output", required=True, help="Output file or directory path.")
    parser.add_argument("--config", default="", help="Optional YAML config path.")
    parser.add_argument("--run-id", default="", help="Pipeline run identifier.")
    return parser


def resolve_run_id(run_id: str | None) -> str:
    if run_id and run_id.strip():
        return run_id.strip()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{now}"


def load_optional_config(config_path: str | Path) -> dict:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return load_yaml(path)
