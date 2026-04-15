from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict

from ..common.id_utils import file_hash, file_type_from_name, make_id
from ..common.models import FileRecord, FileStatus, utc_now_iso
from ..common.state_store import StateStore


RULE_FILE_TYPES = {"rdf", "owl", "ttl"}


class FileService:
    def __init__(self, root_dir: str, store: StateStore) -> None:
        self.root_dir = Path(root_dir)
        self.store = store
        self.upload_dir = self.root_dir / "artifacts" / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def create_record_from_upload(self, source_path: str, original_name: str) -> Dict[str, Any]:
        fid = make_id("file")
        ext = file_type_from_name(original_name)
        target_name = f"{fid}_{original_name}"
        target_path = self.upload_dir / target_name
        shutil.copy2(source_path, target_path)
        now = utc_now_iso()

        record = FileRecord(
            file_id=fid,
            filename=original_name,
            file_type=ext,
            size_bytes=os.path.getsize(target_path),
            path=str(target_path),
            created_at=now,
            updated_at=now,
            status=FileStatus.UPLOADED.value,
            metadata={
                "file_hash": file_hash(str(target_path)),
                "is_rule_file": ext in RULE_FILE_TYPES,
            },
        )
        if ext in RULE_FILE_TYPES:
            record.status = FileStatus.PARSED_SUCCESS.value
            record.metadata["rule_file_state"] = "rule_file"
        self.store.put_file(record)
        return self.store.get_file(fid) or {}

    def list_files(self) -> list[Dict[str, Any]]:
        files = self.store.list_files()
        files.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return files

    def get_file(self, file_id: str) -> Dict[str, Any]:
        return self.store.get_file(file_id) or {}

    def remove_file(self, file_id: str) -> bool:
        payload = self.store.get_file(file_id)
        if not payload:
            return False
        path = payload.get("path")
        if path and Path(path).exists():
            try:
                Path(path).unlink()
            except OSError:
                pass
        self.store.remove_file(file_id)
        return True
