from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.io_utils import ensure_dir, read_json, write_json


class DesktopStateStore:
    def __init__(self, root: str | Path):
        self._root = ensure_dir(root)
        self._path = self._root / "desktop_state.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {
                "active_ontology": None,
                "last_selected_file_id": "",
                "last_preview_file_id": "",
            }
        payload = read_json(self._path)
        if not isinstance(payload, dict):
            return {
                "active_ontology": None,
                "last_selected_file_id": "",
                "last_preview_file_id": "",
            }
        payload.setdefault("active_ontology", None)
        payload.setdefault("last_selected_file_id", "")
        payload.setdefault("last_preview_file_id", "")
        return payload

    def save(self, data: dict[str, Any]) -> None:
        write_json(self._path, data)

    def update(self, **fields: Any) -> dict[str, Any]:
        state = self.load()
        state.update(fields)
        self.save(state)
        return state
