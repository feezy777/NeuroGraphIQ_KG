from __future__ import annotations

from scripts.desktop.services.fine_process_router import FineProcessRouter


def test_route_structured_file() -> None:
    router = FineProcessRouter()
    result = router.route({"file_type": "xlsx"})
    assert result["processor_type"] == "structured_processor"
    assert result["status"] == "placeholder"


def test_route_document_file() -> None:
    router = FineProcessRouter()
    result = router.route({"file_type": "pdf"})
    assert result["processor_type"] == "document_processor"
    assert result["status"] == "placeholder"


def test_route_ontology_file() -> None:
    router = FineProcessRouter()
    result = router.route({"file_type": "owl"})
    assert result["processor_type"] == "ontology_incremental_processor"
