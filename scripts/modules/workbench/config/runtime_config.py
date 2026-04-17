from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# DeepSeek /v1/chat/completions: max_tokens must be in [1, 8192] (API returns 400 otherwise).
DEEPSEEK_CHAT_COMPLETION_MAX_TOKENS = 8192


def clamp_deepseek_max_tokens(value: Any) -> int:
    """Return 0 to omit max_tokens, or an int in [1, DEEPSEEK_CHAT_COMPLETION_MAX_TOKENS]."""
    try:
        mt = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if mt <= 0:
        return 0
    return min(max(mt, 1), DEEPSEEK_CHAT_COMPLETION_MAX_TOKENS)


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
        # 请求稳健性：失败重试，但不自动回退到本地提取（fail-fast）
        "request_timeout_sec": 600,
        "request_retries": 2,
        "retry_backoff_sec": 1.2,
        "force_json_output": True,
        # 单批 completion 输出上限；DeepSeek Chat API 仅允许 [1, 8192]，超出会被拒绝
        "max_tokens": 8192,
        "top_p": 1.0,
        "prompt_version": "region_extract_v2",
        # 表格：单批最大字符（整表可一次送入时尽量大；极长表仍再切）
        "deepseek_batch_max_chars": 500000,
        # 表格：每批最多行数（>0 时优先按行切块，再按字符二次切；避免单批 90+ 行时输出 JSON 被截断）
        "deepseek_rows_per_batch": 12,
        "batch_delay_sec": 0,
        # 为 false 时不对模型输出做本地 KB 名称补全（避免“看起来像模型抽的、实为词典补全”）
        "enrich_from_kb": False,
        # Custom prompts: empty string means "use built-in default"
        "system_prompt": "",
        "user_prompt_prefix": "",
        # 脑区抽取（文件/文本）：预设 id 见 ExtractionService；空则走默认预设
        "region_prompt_preset": "default",
        # 非空则完全覆盖预设 user 内容，需含 {TEXT} 占位符
        "region_user_prompt_template": "",
        # 脑区直接生成：预设 id；空模板则走内置默认/direct 预设
        "direct_region_prompt_preset": "default",
        "direct_region_user_prompt_template": "",
    },
    # Persisted per-center DeepSeek profile overrides.
    # Key is a profile name (e.g. "region_center", "circuit_center", "connection_center",
    # or any user-chosen name). Each value is a partial deepseek dict merged over global.
    "deepseek_profiles": {},
    # Moonshot (Kimi) — OpenAI-compatible API; used by 脑区验证中心 multi-model path.
    "moonshot": {
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.moonshot.cn",
        "model": "moonshot-v1-8k",
        "temperature": 0.2,
        "request_timeout_sec": 120,
        "request_retries": 2,
        "retry_backoff_sec": 1.2,
        # Kimi 兼容接口不支持 response_format=json_object；代码侧对 label=kimi 也会强制关闭
        "force_json_output": False,
        "max_tokens": 2048,
    },
    "pipeline": {
        "auto_parse_on_upload": True,
        "auto_extract_on_parse": False,
        "auto_validate_on_extract": False,
        "normalize_mode_default": "local",
        "validate_mode_default": "local",
        # 脑区提取 v2：仅用于 mode=local 的路径（标准化 + 高召回 + 本地后处理）。
        # mode=deepseek 时始终走 DeepSeek API 分批抽取，不受此项「抢占」；避免未调 API 却显示 region_v2_deepseek。
        "region_extraction_v2": {
            "enabled": False,
            "log_layers": True,
            "deepseek_refine": False,
            "drop_rejected": False,
        },
        # Compiled OWL/RDF -> JSON ruleset; consumed by ValidationService + staging gates.
        "ontology_rules": {
            "enabled": False,
            "path": "artifacts/ontology/ruleset.json",
            "bind_on_extract": True,
            "require_binding_for_confirmed": True,
            "require_known_terms": False,
            # hard: block stage_to_unverified when a rule issue is severity hard; warn: never block (still records ontology_check).
            "stage_policy": "warn",
            "issue_severity": {
                "parent_not_allowed": "hard",
                "invalid_domain_range": "hard",
                "unknown_term": "warn",
                "invalid_class": "warn",
            },
        },
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


def resolve_deepseek_config(
    global_runtime: Dict[str, Any],
    profile_key: Optional[str] = None,
    inline_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve effective DeepSeek config with priority: inline_override > profile > global.

    Args:
        global_runtime: Full runtime dict (from load_runtime).
        profile_key: Name of a persisted profile in runtime['deepseek_profiles'].
        inline_override: A partial deepseek dict passed directly (e.g. from a single request).

    Returns:
        Flat deepseek config dict ready for ExtractionService.
    """
    global_deepseek = dict(global_runtime.get("deepseek", {}))

    # Step 1: merge persisted profile over global (if any)
    profiles = global_runtime.get("deepseek_profiles", {})
    if profile_key and profile_key in profiles:
        profile_cfg = profiles[profile_key] or {}
        # Profile may omit api_key; if empty, inherit from global
        merged = _deep_merge(global_deepseek, {k: v for k, v in profile_cfg.items() if v != ""})
        config_source = f"profile:{profile_key}"
    else:
        merged = global_deepseek
        config_source = "global"

    # Step 2: merge inline one-shot override on top (highest priority)
    if inline_override:
        merged = _deep_merge(merged, {k: v for k, v in inline_override.items() if v != ""})
        config_source = "inline_override"
        # 若本次请求只指定了「预设 id」而未带自定义模板，则不应沿用 profile 里旧的整段模板
        if "region_prompt_preset" in inline_override and "region_user_prompt_template" not in inline_override:
            merged.pop("region_user_prompt_template", None)
        if "direct_region_prompt_preset" in inline_override and "direct_region_user_prompt_template" not in inline_override:
            merged.pop("direct_region_user_prompt_template", None)

    return {
        "enabled": bool(merged.get("enabled")),
        "api_key": merged.get("api_key", ""),
        "base_url": merged.get("base_url", "https://api.deepseek.com"),
        "model": merged.get("model", "deepseek-chat"),
        "temperature": float(merged.get("temperature", 0.2)),
        "system_prompt": merged.get("system_prompt", ""),
        "user_prompt_prefix": merged.get("user_prompt_prefix", ""),
        "region_prompt_preset": merged.get("region_prompt_preset", "default"),
        "region_user_prompt_template": merged.get("region_user_prompt_template", ""),
        "direct_region_prompt_preset": merged.get("direct_region_prompt_preset", "default"),
        "direct_region_user_prompt_template": merged.get("direct_region_user_prompt_template", ""),
        # 稳定性与 JSON 输出控制（从 DEFAULT_RUNTIME["deepseek"] 透传）
        "request_timeout_sec": int(merged.get("request_timeout_sec", 600)),
        "request_retries": int(merged.get("request_retries", 2)),
        "retry_backoff_sec": float(merged.get("retry_backoff_sec", 1.2)),
        "force_json_output": bool(merged.get("force_json_output", True)),
        # 0 = 不传 max_tokens；否则钳制到 DeepSeek API 允许范围
        "max_tokens": clamp_deepseek_max_tokens(merged.get("max_tokens", DEEPSEEK_CHAT_COMPLETION_MAX_TOKENS)),
        "top_p": float(merged.get("top_p", 1.0)),
        "prompt_version": str(merged.get("prompt_version", "region_extract_v2")),
        "deepseek_batch_max_chars": int(merged.get("deepseek_batch_max_chars", 500000)),
        "deepseek_rows_per_batch": int(merged.get("deepseek_rows_per_batch", 12) or 0),
        "batch_delay_sec": float(merged.get("batch_delay_sec", 0)),
        "enrich_from_kb": bool(merged.get("enrich_from_kb", False)),
        "_config_source": config_source,
    }


def resolve_moonshot_config(global_runtime: Dict[str, Any]) -> Dict[str, Any]:
    """Flat Moonshot/Kimi config for chat completions (validation center)."""
    m = dict(global_runtime.get("moonshot") or {})
    return {
        "enabled": bool(m.get("enabled")),
        "api_key": str(m.get("api_key", "") or ""),
        "base_url": str(m.get("base_url", "https://api.moonshot.cn")),
        "model": str(m.get("model", "moonshot-v1-8k")),
        "temperature": float(m.get("temperature", 0.2)),
        "request_timeout_sec": int(m.get("request_timeout_sec", 120)),
        "request_retries": int(m.get("request_retries", 2)),
        "retry_backoff_sec": float(m.get("retry_backoff_sec", 1.2)),
        "force_json_output": bool(m.get("force_json_output", True)),
        "max_tokens": clamp_deepseek_max_tokens(m.get("max_tokens", 2048)),
    }


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
