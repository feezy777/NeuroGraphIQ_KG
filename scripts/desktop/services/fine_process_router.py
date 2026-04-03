from __future__ import annotations

from typing import Any

STRUCTURED_TYPES = {"xlsx", "csv", "tsv", "json", "jsonl"}
ONTOLOGY_TYPES = {"rdf", "owl", "xml"}
DOCUMENT_TYPES = {"txt", "md", "pdf", "docx"}


class FineProcessRouter:
    def route(self, file_record: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(file_record, dict):
            return {
                "processor_type": "unknown_processor",
                "status": "placeholder",
                "input_contract": {},
                "output_contract": {},
            }

        file_type = str(file_record.get("file_type") or "").lower()
        if file_type in STRUCTURED_TYPES:
            processor_type = "structured_processor"
            input_contract = {"required": ["file_id", "normalized_table_rows"], "optional": ["column_mapping"]}
            output_contract = {"produces": ["structured_features", "validation_hints", "semantic_candidates"]}
        elif file_type in ONTOLOGY_TYPES:
            processor_type = "ontology_incremental_processor"
            input_contract = {"required": ["file_id", "ontology_baseline_version"], "optional": ["mapping_overrides"]}
            output_contract = {"produces": ["ontology_delta_candidates", "mapping_alignment_suggestions"]}
        elif file_type in DOCUMENT_TYPES:
            processor_type = "document_processor"
            input_contract = {"required": ["file_id", "normalized_text"], "optional": ["section_hints", "keyword_hints"]}
            output_contract = {"produces": ["document_entities", "document_relations", "evidence_candidates"]}
        else:
            processor_type = "generic_processor"
            input_contract = {"required": ["file_id"]}
            output_contract = {"produces": ["generic_preprocess_artifact"]}

        return {
            "processor_type": processor_type,
            "status": "placeholder",
            "input_contract": input_contract,
            "output_contract": output_contract,
        }
