from __future__ import annotations

from typing import Any, Dict, List

from ..common.models import utc_now_iso


class NormalizationService:
    def build_normalized_payload(self, file_payload: Dict[str, Any], parsed_payload: Dict[str, Any]) -> Dict[str, Any]:
        doc = parsed_payload.get("document") or {}
        chunks: List[Dict[str, Any]] = parsed_payload.get("chunks", [])

        document_layer = {
            "file_id": file_payload.get("file_id", ""),
            "file_type": file_payload.get("file_type", ""),
            "title": doc.get("title", ""),
            "source": doc.get("source", ""),
            "authors": doc.get("authors", []),
            "year": doc.get("year", None),
            "doi": doc.get("doi", ""),
            "page_range": doc.get("page_range", ""),
            "parse_status": doc.get("parse_status", ""),
            "normalized_at": utc_now_iso(),
        }

        content_chunk_layer = {
            "raw_text": doc.get("raw_text", ""),
            "paragraphs": doc.get("paragraphs", []),
            "sentences": doc.get("sentences", []),
            "table_cells": doc.get("table_cells", []),
            "figure_captions": doc.get("figure_captions", []),
            "heading_levels": doc.get("heading_levels", []),
            "ocr_blocks": doc.get("ocr_blocks", []),
            "chunks": chunks,
        }

        candidate_knowledge_unit_layer = {
            "candidate_regions": [],
            "candidate_entities": [],
            "candidate_relations": [],
            "candidate_attributes": [],
            "candidate_circuits": [],
            "candidate_connections": [],
            "candidate_evidence_fragments": [],
        }

        return {
            "document_layer": document_layer,
            "content_chunk_layer": content_chunk_layer,
            "candidate_knowledge_unit_layer": candidate_knowledge_unit_layer,
        }
