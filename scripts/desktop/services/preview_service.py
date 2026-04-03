from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.desktop.models import GateDecision
from scripts.services.file_validation_center import get_file_content, get_file_preview, get_file_report


class PreviewService:
    def __init__(self, file_center_root: str | Path):
        self._root = Path(file_center_root)

    def get_preview(
        self,
        file_id: str,
        page: int = 1,
        page_size: int = 200,
        mode: str = "auto",
        gate_decision: GateDecision | None = None,
    ) -> dict[str, Any]:
        if gate_decision and not gate_decision.allow_preview:
            raise PermissionError(f"preview_blocked:{gate_decision.block_reason}")

        preview = get_file_preview(file_id=file_id, root=self._root, page=page, page_size=page_size, view=mode)
        if preview.get("mode") == "raw_embed":
            content = get_file_content(file_id=file_id, root=self._root)
            preview["embed_path"] = str(Path(str(content.get("path", ""))).resolve())
        return preview

    def get_report(self, file_id: str, gate_decision: GateDecision | None = None) -> dict[str, Any]:
        if gate_decision and not gate_decision.allow_preview:
            raise PermissionError(f"preview_blocked:{gate_decision.block_reason}")
        return get_file_report(file_id=file_id, root=self._root)
