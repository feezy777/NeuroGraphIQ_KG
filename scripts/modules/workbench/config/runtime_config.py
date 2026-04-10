from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULT_RUNTIME: Dict[str, Any] = {
    "database": {
        "backend": "postgres",
        "admin_db": {
            "host": "localhost",
            "port": 5432,
            "dbname": "postgres",
            "user": "postgres",
            "password": "root",
        },
        "workbench_db": {
            "host": "localhost",
            "port": 5432,
            "dbname": "NeuroGraphIQ_Workbench",
            "schema": "workbench",
            "user": "postgres",
            "password": "root",
        },
        "unverified_db": {
            "host": "localhost",
            "port": 5432,
            "dbname": "NeuroGraphIQ_KG_Unverified",
            "schema": "neurokg_unverified",
            "user": "postgres",
            "password": "root",
        },
        "production_db": {
            "host": "localhost",
            "port": 5432,
            "dbname": "NeuroGraphIQ_KG",
            "schema": "neurokg",
            "user": "postgres",
            "password": "root",
        },
    },
    "deepseek": {
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "temperature": 0.2,
    },
    "pipeline": {
        "auto_parse_on_upload": True,
        "auto_extract_on_parse": False,
        "auto_validate_on_extract": False,
        "normalize_mode_default": "local",
        "validate_mode_default": "local",
    },
    "ui": {"language": "zh-CN"},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_runtime(root_dir: str) -> Dict[str, Any]:
    runtime_path = Path(root_dir) / "configs" / "local" / "runtime.local.yaml"
    if not runtime_path.exists():
        return dict(DEFAULT_RUNTIME)
    data = yaml.safe_load(runtime_path.read_text(encoding="utf-8")) or {}
    return _deep_merge(DEFAULT_RUNTIME, data)


def save_runtime(root_dir: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    runtime_path = Path(root_dir) / "configs" / "local" / "runtime.local.yaml"
    current = load_runtime(root_dir)
    merged = _deep_merge(current, payload)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return merged


def resolve_model_config(global_runtime: Dict[str, Any], task_override: Dict[str, Any] | None = None) -> Dict[str, Any]:
    override = task_override or {}
    deepseek_global = global_runtime.get("deepseek", {})
    merged = _deep_merge(deepseek_global, override.get("deepseek", {}))
    return {
        "config_source": "task_override" if override.get("deepseek") else "global",
        "deepseek_enabled": bool(merged.get("enabled")),
        "deepseek_api_key": merged.get("api_key", ""),
        "deepseek_base_url": merged.get("base_url", ""),
        "deepseek_model": merged.get("model", ""),
        "deepseek_temperature": float(merged.get("temperature", 0.2)),
        "routing_policy": override.get("routing_policy", "single_model"),
        "param_version": override.get("param_version", "v0"),
        "task_overrides": override,
    }


def db_config(runtime: Dict[str, Any], key: str) -> Dict[str, Any]:
    return runtime.get("database", {}).get(key, {})
