from __future__ import annotations

from pathlib import Path

from scripts.desktop.services.ontology_service import OntologyService
from scripts.desktop.state_store import DesktopStateStore


def test_ontology_gate_requires_import(tmp_path: Path) -> None:
    state = DesktopStateStore(tmp_path / "state")
    service = OntologyService(state_store=state, persist_runtime_config=False)
    gate = service.gate_decision()
    assert gate.allow_preprocess is False
    assert gate.allow_preview is False
    assert gate.block_reason == "ontology_not_imported"


def test_import_rdfxml_sets_active_baseline(tmp_path: Path) -> None:
    ontology_path = tmp_path / "sample.rdf"
    ontology_path.write_text(
        """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:neuro="http://example.org/neuro#">
  <owl:Class rdf:about="http://example.org/neuro#Organism"/>
</rdf:RDF>
""",
        encoding="utf-8",
    )

    state = DesktopStateStore(tmp_path / "state")
    service = OntologyService(state_store=state, persist_runtime_config=False)
    result = service.import_ontology(ontology_path)

    assert result.success is True
    active = service.active_baseline()
    assert active is not None
    assert active.source_path.endswith("sample.rdf")
    gate = service.gate_decision()
    assert gate.allow_preprocess is True
    assert gate.allow_preview is True
