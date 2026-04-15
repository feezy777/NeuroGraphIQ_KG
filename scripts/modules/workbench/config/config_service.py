from __future__ import annotations

from typing import Any, Dict, Optional

from .runtime_config import load_runtime, resolve_deepseek_config, resolve_model_config, save_runtime


# 作用：统一管理运行配置，尤其是 DeepSeek 的全局配置和个性化配置。
# 步骤：上层业务先调用 ConfigService -> 它再去读写 runtime.local.yaml 或解析最终配置。
# 注意：配置优先级逻辑最好集中写在这里，避免前后端各写一套。
class ConfigService:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir

    # 作用：读取当前完整运行配置。
    # 步骤：委托给 runtime_config.load_runtime。
    # 注意：这是多数配置读取流程的基础入口。
    def get_runtime(self) -> Dict[str, Any]:
        return load_runtime(self.root_dir)

    # 作用：把新的配置片段合并并保存到本地运行配置文件。
    # 步骤：调用 save_runtime -> 做 deep merge -> 持久化到 yaml。
    # 注意：这里是“增量更新”，不是整份配置全量覆盖。
    def update_runtime(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return save_runtime(self.root_dir, payload)

    # 作用：给前端配置中心返回“原始 runtime + 解析后的模型配置”。
    # 步骤：先读 runtime -> 再调用 resolve_model_config 得到最终展示结果。
    # 注意：这个接口更偏“给前端看”，不一定直接用于真实抽取执行。
    def get_model_center_payload(self, task_override: Dict[str, Any] | None = None) -> Dict[str, Any]:
        runtime = self.get_runtime()
        merged = resolve_model_config(runtime, task_override)
        return {"runtime": runtime, "resolved_model_config": merged}

    # ---- DeepSeek profile management ----

    def list_deepseek_profiles(self) -> Dict[str, Any]:
        """Return all persisted profiles (without api_key values for security)."""
        runtime = self.get_runtime()
        profiles = runtime.get("deepseek_profiles", {})
        safe = {}
        for name, cfg in profiles.items():
            safe[name] = {k: (v if k != "api_key" else ("***" if v else "")) for k, v in (cfg or {}).items()}
        return safe

    def save_deepseek_profile(self, profile_key: str, profile_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a named DeepSeek profile. Merges over any existing profile with the same key."""
        runtime = self.get_runtime()
        existing_profiles = runtime.get("deepseek_profiles", {})
        existing_profile = existing_profiles.get(profile_key, {})
        # If api_key is empty string in new cfg, keep the existing one
        if not profile_cfg.get("api_key") and existing_profile.get("api_key"):
            profile_cfg = dict(profile_cfg)
            profile_cfg["api_key"] = existing_profile["api_key"]
        existing_profiles[profile_key] = profile_cfg
        return self.update_runtime({"deepseek_profiles": existing_profiles})

    def delete_deepseek_profile(self, profile_key: str) -> Dict[str, Any]:
        """Remove a named DeepSeek profile."""
        runtime = self.get_runtime()
        profiles = runtime.get("deepseek_profiles", {})
        profiles.pop(profile_key, None)
        return self.update_runtime({"deepseek_profiles": profiles})

    # 作用：解析某次实际执行时最终要使用的 DeepSeek 配置。
    # 步骤：读取 runtime -> 按 inline_override > profile > global 的优先级合并。
    # 注意：真正执行抽取/生成时，应该统一走这个函数。
    def resolve_effective_deepseek(
        self,
        profile_key: Optional[str] = None,
        inline_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve effective DeepSeek config: inline_override > profile > global."""
        runtime = self.get_runtime()
        return resolve_deepseek_config(runtime, profile_key=profile_key, inline_override=inline_override)

    def get_public_effective_deepseek(
        self,
        profile_key: Optional[str] = None,
        inline_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Same as resolve_effective_deepseek but safe for JSON (no raw api_key)."""
        cfg = self.resolve_effective_deepseek(profile_key=profile_key, inline_override=inline_override)
        return {
            "enabled": bool(cfg.get("enabled")),
            "api_key_set": bool(cfg.get("api_key")),
            "model": cfg.get("model", "deepseek-chat"),
            "base_url": cfg.get("base_url", "https://api.deepseek.com"),
            "temperature": float(cfg.get("temperature", 0.2)),
            "cfg_source": cfg.get("_config_source", "global"),
            "region_prompt_preset": cfg.get("region_prompt_preset", "default"),
            "direct_region_prompt_preset": cfg.get("direct_region_prompt_preset", "default"),
        }
