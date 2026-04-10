from __future__ import annotations

from typing import Any, Dict

from .runtime_config import load_runtime, resolve_model_config, save_runtime


class ConfigService:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir

    def get_runtime(self) -> Dict[str, Any]:
        return load_runtime(self.root_dir)

    def update_runtime(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return save_runtime(self.root_dir, payload)

    def get_model_center_payload(self, task_override: Dict[str, Any] | None = None) -> Dict[str, Any]:
        runtime = self.get_runtime()
        merged = resolve_model_config(runtime, task_override)
        return {"runtime": runtime, "resolved_model_config": merged}
