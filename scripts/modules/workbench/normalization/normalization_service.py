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

        table_rows: List[Dict[str, Any]] = doc.get("table_rows") or []
        # 只保留摘要字段在 normalized_payload 里，避免把完整 table_cells / chunks（可能数千条）
        # 也写入 uploaded_file.metadata_json，导致 HTTP 响应过大、页面渲染卡顿。
        # 完整数据可通过 /api/files/<id>/parsed 或 content_chunk 表单独获取。
        content_chunk_layer = {
            # 表格型文件（xlsx/xls/csv）的逐行结构化数据，是抽取阶段的主要输入
            "row_count": len(table_rows),
            "sheet_names": list({r.get("sheet", "Sheet1") for r in table_rows}) if table_rows else [],
            "preview_rows": table_rows[:20],      # 只存前 20 行作为预览
            "chunk_count": len(chunks),           # 只记录 chunk 数量，不存完整列表
            "has_raw_text": bool(doc.get("raw_text", "")),
            "paragraph_count": len(doc.get("paragraphs", [])),
            "table_cell_count": len(doc.get("table_cells", [])),
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
