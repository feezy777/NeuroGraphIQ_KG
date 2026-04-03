from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


DEFAULT_RUNTIME_CONFIG: dict[str, Any] = {
    "database": {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "database": os.getenv("PGDATABASE", "neurographiq_kg_v2"),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", "root"),
        "schema": os.getenv("PGSCHEMA", "neurokg"),
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    },
    "excel": {
        "path": r"D:\Fuyao\福耀实习\文档\Brain volume list.xlsx",
        "sheet_index": 1,
        "header_row": 1,
    },
    "ontology": {
        "path": str((PROJECT_ROOT / "ontology" / "source" / "NeuroGraphIQ_KG.rdf").resolve()),
    },
    "pipeline": {
        "use_deepseek": True,
        "batch_size": 60,
        "load_scope": "all_mappable",
        "major_circuit_target_multiplier": 1.8,
        "major_circuit_region_batch_size": 24,
        "major_circuit_max_calls": 8,
    },
    "ui": {
        "language": "zh",
    },
}


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {"1", 1, "true", "True", "yes", "on"}:
        return True
    if value in {"0", 0, "false", "False", "no", "off"}:
        return False
    return default


def _to_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _unwrap_deepseek_override(override: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(override, dict):
        return {}
    nested = override.get("deepseek")
    if isinstance(nested, dict):
        merged = dict(nested)
        # allow top-level enabled switch for convenience
        if "enabled" in override:
            merged.setdefault("enabled", override.get("enabled"))
        if "use_deepseek" in override:
            merged.setdefault("enabled", override.get("use_deepseek"))
        if "useDeepSeek" in override:
            merged.setdefault("enabled", override.get("useDeepSeek"))
        return merged
    return dict(override)


def normalize_deepseek_config(raw: dict[str, Any] | None, *, default_enabled: bool = True) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    enabled = _to_bool(
        data.get("enabled", data.get("use_deepseek", data.get("useDeepSeek", default_enabled))),
        default_enabled,
    )
    return {
        "enabled": enabled,
        "api_key": _to_text(data.get("api_key", data.get("apiKey", ""))),
        "base_url": _to_text(data.get("base_url", data.get("baseUrl", "https://api.deepseek.com")), "https://api.deepseek.com"),
        "model": _to_text(data.get("model", "deepseek-chat"), "deepseek-chat"),
    }


def resolve_deepseek_config(runtime: dict[str, Any], override: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    global_raw = {
        "enabled": bool(runtime.get("pipeline", {}).get("use_deepseek", True)),
        "api_key": runtime.get("deepseek", {}).get("api_key", ""),
        "base_url": runtime.get("deepseek", {}).get("base_url", "https://api.deepseek.com"),
        "model": runtime.get("deepseek", {}).get("model", "deepseek-chat"),
    }
    global_cfg = normalize_deepseek_config(global_raw, default_enabled=True)
    override_raw = _unwrap_deepseek_override(override)
    if not override_raw:
        return global_cfg, "global"

    override_cfg = normalize_deepseek_config(override_raw, default_enabled=global_cfg["enabled"])
    final_cfg = dict(global_cfg)
    source = "global"

    if any(key in override_raw for key in ("enabled", "use_deepseek", "useDeepSeek")):
        final_cfg["enabled"] = bool(override_cfg["enabled"])
        source = "override"
    if "api_key" in override_raw or "apiKey" in override_raw:
        if override_cfg["api_key"]:
            final_cfg["api_key"] = override_cfg["api_key"]
            source = "override"
    if "base_url" in override_raw or "baseUrl" in override_raw:
        if override_cfg["base_url"]:
            final_cfg["base_url"] = override_cfg["base_url"]
            source = "override"
    if "model" in override_raw:
        if override_cfg["model"]:
            final_cfg["model"] = override_cfg["model"]
            source = "override"

    if not final_cfg["base_url"]:
        final_cfg["base_url"] = "https://api.deepseek.com"
    if not final_cfg["model"]:
        final_cfg["model"] = "deepseek-chat"
    return final_cfg, source


def resolve_runtime_deepseek(runtime: dict[str, Any], override: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    merged_runtime = _deep_merge(DEFAULT_RUNTIME_CONFIG, runtime or {})
    final_cfg, source = resolve_deepseek_config(merged_runtime, override)
    merged_runtime.setdefault("pipeline", {})
    merged_runtime.setdefault("deepseek", {})
    merged_runtime["pipeline"]["use_deepseek"] = bool(final_cfg["enabled"])
    merged_runtime["deepseek"]["api_key"] = final_cfg["api_key"]
    merged_runtime["deepseek"]["base_url"] = final_cfg["base_url"]
    merged_runtime["deepseek"]["model"] = final_cfg["model"]
    merged_runtime["_deepseek_resolve"] = {
        "source": source,
        "override_applied": source == "override",
        "enabled": bool(final_cfg["enabled"]),
        "base_url": final_cfg["base_url"],
        "model": final_cfg["model"],
    }
    return merged_runtime, dict(merged_runtime["_deepseek_resolve"])


def runtime_config_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    return PROJECT_ROOT / "configs" / "local" / "runtime.local.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_runtime_config(path: str | Path | None = None) -> dict[str, Any]:
    target = runtime_config_path(path)
    merged = deepcopy(DEFAULT_RUNTIME_CONFIG)
    if target.exists():
        content = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if isinstance(content, dict):
            merged = _deep_merge(merged, content)
    return merged


def save_runtime_config(config: dict[str, Any], path: str | Path | None = None) -> Path:
    target = runtime_config_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    merged = _deep_merge(DEFAULT_RUNTIME_CONFIG, config or {})
    target.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target


def apply_runtime_env(config: dict[str, Any]) -> None:
    db = config.get("database", {})
    ds = config.get("deepseek", {})
    os.environ["PGHOST"] = str(db.get("host", "localhost"))
    os.environ["PGPORT"] = str(db.get("port", "5432"))
    os.environ["PGDATABASE"] = str(db.get("database", "neurographiq_kg_v2"))
    os.environ["PGUSER"] = str(db.get("user", "postgres"))
    os.environ["PGPASSWORD"] = str(db.get("password", ""))
    os.environ["PGSCHEMA"] = str(db.get("schema", "neurokg"))

    os.environ["DEEPSEEK_API_KEY"] = str(ds.get("api_key", ""))
    os.environ["DEEPSEEK_BASE_URL"] = str(ds.get("base_url", "https://api.deepseek.com"))
    os.environ["DEEPSEEK_MODEL"] = str(ds.get("model", "deepseek-chat"))


def redact_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    masked = deepcopy(config)
    if masked.get("database", {}).get("password"):
        masked["database"]["password"] = "***"
    if masked.get("deepseek", {}).get("api_key"):
        masked["deepseek"]["api_key"] = "***"
    return masked

