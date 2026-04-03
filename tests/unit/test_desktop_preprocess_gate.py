from __future__ import annotations

from pathlib import Path

from scripts.desktop.models import GateDecision
from scripts.desktop.services.preprocess_service import PreprocessService


def test_preprocess_enqueue_blocked_by_gate(tmp_path: Path) -> None:
    service = PreprocessService(
        file_center_root=tmp_path / "file_center",
        runtime_provider=lambda: {},
        gate_provider=lambda: GateDecision(
            allow_preprocess=False,
            allow_preview=False,
            allow_fine_process=False,
            allow_load=False,
            block_reason="ontology_not_imported",
        ),
    )
    try:
        task = service.enqueue("file_demo")
        assert task["status"] == "blocked"
        assert task["error_message"] == "ontology_not_imported"
    finally:
        service.shutdown()
