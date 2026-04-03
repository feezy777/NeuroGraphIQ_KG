from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.services.file_validation_center import list_files, register_local_file_path


class FileService:
    def __init__(self, file_center_root: str | Path):
        self._root = Path(file_center_root)

    def import_files(self, paths: list[str | Path], linked_ontology_version: str) -> list[dict[str, Any]]:
        imported: list[dict[str, Any]] = []
        for item in paths:
            source = Path(item).expanduser().resolve()
            metadata = {"linked_ontology_version": linked_ontology_version or ""}
            record = register_local_file_path(source, self._root, metadata=metadata)
            imported.append(record)
        return imported

    def list_files(self) -> dict[str, Any]:
        return list_files(self._root)

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        listing = self.list_files()
        for item in listing.get("files", []):
            if str(item.get("file_id")) == file_id:
                return item
        return None
