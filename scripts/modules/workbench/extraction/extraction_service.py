from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from urllib import error, request

from ..common.id_utils import make_id
from ..common.models import CandidateCircuit, CandidateConnection, CandidateRegion, utc_now_iso


REGION_HINTS = [
    "cortex",
    "hippocampus",
    "thalamus",
    "amygdala",
    "insula",
    "striatum",
    "brainstem",
    "皮层",
    "海马",
    "丘脑",
    "杏仁核",
    "脑区",
]


def _guess_granularity(name: str) -> str:
    s = (name or "").lower()
    if "allen" in s:
        return "allen"
    if "sub" in s or "nucleus" in s:
        return "sub"
    if "major" in s or "lobe" in s or "cortex" in s:
        return "major"
    return "unknown"


def _guess_laterality(text: str) -> str:
    s = (text or "").lower()
    if any(k in s for k in ["left", "左"]):
        return "left"
    if any(k in s for k in ["right", "右"]):
        return "right"
    if any(k in s for k in ["bilateral", "双侧"]):
        return "bilateral"
    return "unknown"


def _extract_name_from_line(line: str) -> str:
    cleaned = re.sub(r"[\t|,;]+", " ", line).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > 120:
        cleaned = cleaned[:120]
    return cleaned


class ExtractionService:
    def run_region_extraction(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        mode: str,
        deepseek_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        chunks = parsed_payload.get("chunks", [])
        parsed_doc = parsed_payload.get("document", {})
        parsed_document_id = parsed_doc.get("parsed_document_id", "")
        if mode == "deepseek":
            candidates = self._extract_by_deepseek(file_payload, chunks, parsed_document_id, deepseek_cfg)
            return {"method": "deepseek", "llm_model": deepseek_cfg.get("model", ""), "candidates": candidates}
        candidates = self._extract_by_local_rules(file_payload, chunks, parsed_document_id)
        return {"method": "local_rule", "llm_model": "", "candidates": candidates}

    def _extract_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        parsed_document_id: str,
    ) -> List[CandidateRegion]:
        rows: List[CandidateRegion] = []
        seen: set[str] = set()
        for ch in chunks[:500]:
            text = (ch.get("text_content") or "").strip()
            if not text:
                continue
            lower = text.lower()
            if not any(h in lower for h in REGION_HINTS):
                continue
            name = _extract_name_from_line(text)
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                CandidateRegion(
                    id=make_id("cr"),
                    file_id=file_payload.get("file_id", ""),
                    parsed_document_id=parsed_document_id,
                    chunk_id=ch.get("chunk_id", ""),
                    source_text=text,
                    en_name_candidate=name if all(ord(c) < 128 for c in name) else "",
                    cn_name_candidate=name if any(ord(c) > 127 for c in name) else "",
                    alias_candidates=[],
                    laterality_candidate=_guess_laterality(text),
                    region_category_candidate="brain_region",
                    granularity_candidate=_guess_granularity(name),
                    parent_region_candidate="",
                    ontology_source_candidate="local_rule_extract",
                    confidence=0.62,
                    extraction_method="local_rule",
                    llm_model="",
                    status="pending_review",
                    created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
            )
        if not rows:
            rows.append(
                CandidateRegion(
                    id=make_id("cr"),
                    file_id=file_payload.get("file_id", ""),
                    parsed_document_id=parsed_document_id,
                    chunk_id="",
                    source_text=file_payload.get("filename", ""),
                    en_name_candidate=file_payload.get("filename", ""),
                    cn_name_candidate="",
                    alias_candidates=[],
                    laterality_candidate="unknown",
                    region_category_candidate="brain_region",
                    granularity_candidate="unknown",
                    parent_region_candidate="",
                    ontology_source_candidate="local_rule_fallback",
                    confidence=0.3,
                    extraction_method="local_rule",
                    llm_model="",
                    status="pending_review",
                    created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
            )
        return rows

    def _extract_by_deepseek(
        self,
        file_payload: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        parsed_document_id: str,
        deepseek_cfg: Dict[str, Any],
    ) -> List[CandidateRegion]:
        if not deepseek_cfg.get("enabled"):
            raise RuntimeError("deepseek_disabled")
        if not deepseek_cfg.get("api_key"):
            raise RuntimeError("deepseek_api_key_missing")

        sample = "\n".join((ch.get("text_content") or "")[:180] for ch in chunks[:20])
        if not sample:
            sample = file_payload.get("filename", "")

        prompt = (
            "从以下文本中抽取脑区候选。返回JSON数组，每项字段："
            "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,confidence,source_text。"
            "granularity_candidate只允许major/sub/allen/unknown。\n\n"
            f"TEXT:\n{sample}"
        )

        url = deepseek_cfg.get("base_url", "https://api.deepseek.com").rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": deepseek_cfg.get("model", "deepseek-chat"),
            "temperature": deepseek_cfg.get("temperature", 0.2),
            "messages": [
                {"role": "system", "content": "你是脑区知识图谱抽取助手，只返回JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {deepseek_cfg.get('api_key', '')}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
        except error.HTTPError as exc:  # pragma: no cover
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"deepseek_http_{exc.code}:{detail[:300]}") from exc
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"deepseek_request_failed:{exc}") from exc

        msg = self._parse_chat_text(body)
        parsed_rows = self._parse_json_rows(msg)
        out: List[CandidateRegion] = []
        for row in parsed_rows:
            out.append(
                CandidateRegion(
                    id=make_id("cr"),
                    file_id=file_payload.get("file_id", ""),
                    parsed_document_id=parsed_document_id,
                    chunk_id="",
                    source_text=str(row.get("source_text", "")),
                    en_name_candidate=str(row.get("en_name_candidate", "")),
                    cn_name_candidate=str(row.get("cn_name_candidate", "")),
                    alias_candidates=list(row.get("alias_candidates", [])),
                    laterality_candidate=str(row.get("laterality_candidate", "unknown")),
                    region_category_candidate=str(row.get("region_category_candidate", "brain_region")),
                    granularity_candidate=str(row.get("granularity_candidate", "unknown")),
                    parent_region_candidate=str(row.get("parent_region_candidate", "")),
                    ontology_source_candidate="deepseek_extract",
                    confidence=float(row.get("confidence", 0.7)),
                    extraction_method="deepseek",
                    llm_model=deepseek_cfg.get("model", ""),
                    status="pending_review",
                    created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
            )
        if not out:
            raise RuntimeError("deepseek_empty_result")
        return out

    @staticmethod
    def _parse_chat_text(body: str) -> str:
        payload = json.loads(body)
        choices = payload.get("choices", [])
        if not choices:
            return "[]"
        content = choices[0].get("message", {}).get("content", "")
        return content or "[]"

    @staticmethod
    def _parse_json_rows(text: str) -> List[Dict[str, Any]]:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("regions", [])
        if not isinstance(data, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in data:
            if isinstance(row, dict):
                out.append(row)
        return out

    def run_circuit_extraction(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        mode: str,
        deepseek_cfg: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if mode == "deepseek":
            # phase-1 minimal: keep mode tag but reuse deterministic local build
            rows = self._extract_circuit_by_local_rules(file_payload, parsed_payload, region_candidates, extraction_method="deepseek_placeholder")
            return {"method": "deepseek_placeholder", "llm_model": deepseek_cfg.get("model", ""), "candidates": rows}
        rows = self._extract_circuit_by_local_rules(file_payload, parsed_payload, region_candidates, extraction_method="local_rule")
        return {"method": "local_rule", "llm_model": "", "candidates": rows}

    def _extract_circuit_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
        extraction_method: str,
    ) -> List[CandidateCircuit]:
        parsed_doc = parsed_payload.get("document", {})
        parsed_document_id = parsed_doc.get("parsed_document_id", "")
        reviewed_regions = [r for r in (region_candidates or []) if r.get("status") in {"reviewed", "approved", "staged", "committed"}]
        granularity = "major"
        if reviewed_regions:
            granularity = (reviewed_regions[0].get("granularity_candidate") or "major").strip().lower()
        nodes: List[Dict[str, Any]] = []
        max_nodes = max(1, min(3, len(reviewed_regions)))
        for idx, region in enumerate(reviewed_regions[:max_nodes], start=1):
            nodes.append(
                {
                    "id": make_id("ccn"),
                    "region_id_candidate": (region.get("parent_region_candidate") or "").strip(),
                    "granularity_candidate": (region.get("granularity_candidate") or granularity).strip().lower(),
                    "node_order": idx,
                    "role_label": "relay",
                }
            )
        if not nodes:
            nodes = [
                {
                    "id": make_id("ccn"),
                    "region_id_candidate": "",
                    "granularity_candidate": granularity,
                    "node_order": 1,
                    "role_label": "seed",
                }
            ]

        row = CandidateCircuit(
            id=make_id("cc"),
            file_id=file_payload.get("file_id", ""),
            parsed_document_id=parsed_document_id,
            source_text=(parsed_doc.get("raw_text") or file_payload.get("filename", ""))[:300],
            en_name_candidate=f"Circuit from {file_payload.get('filename', 'file')}",
            cn_name_candidate="",
            alias_candidates=[],
            description_candidate="auto extracted candidate circuit",
            circuit_kind_candidate="inferred",
            loop_type_candidate="inferred",
            cycle_verified_candidate=False,
            confidence_circuit=0.55,
            granularity_candidate=granularity if granularity in {"major", "sub", "allen"} else "major",
            extraction_method=extraction_method,
            llm_model="",
            status="pending_review",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        payload = row.__dict__.copy()
        payload["nodes"] = nodes
        return [payload]

    def run_connection_extraction(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        mode: str,
        deepseek_cfg: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if mode == "deepseek":
            rows = self._extract_connection_by_local_rules(
                file_payload,
                parsed_payload,
                region_candidates,
                extraction_method="deepseek_placeholder",
                llm_model=deepseek_cfg.get("model", ""),
            )
            return {"method": "deepseek_placeholder", "llm_model": deepseek_cfg.get("model", ""), "candidates": rows}
        rows = self._extract_connection_by_local_rules(
            file_payload,
            parsed_payload,
            region_candidates,
            extraction_method="local_rule",
            llm_model="",
        )
        return {"method": "local_rule", "llm_model": "", "candidates": rows}

    def _extract_connection_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
        extraction_method: str,
        llm_model: str,
    ) -> List[Dict[str, Any]]:
        parsed_doc = parsed_payload.get("document", {})
        parsed_document_id = parsed_doc.get("parsed_document_id", "")
        reviewed_regions = [r for r in (region_candidates or []) if r.get("status") in {"reviewed", "approved", "staged", "committed"}]
        granularity = "major"
        if reviewed_regions:
            granularity = (reviewed_regions[0].get("granularity_candidate") or "major").strip().lower()
            if granularity not in {"major", "sub", "allen"}:
                granularity = "major"

        src_ref = ""
        tgt_ref = ""
        for region in reviewed_regions:
            rid = (region.get("parent_region_candidate") or "").strip()
            if not src_ref and rid:
                src_ref = rid
            elif not tgt_ref and rid and rid != src_ref:
                tgt_ref = rid
            if src_ref and tgt_ref:
                break

        row = CandidateConnection(
            id=make_id("ccn"),
            file_id=file_payload.get("file_id", ""),
            parsed_document_id=parsed_document_id,
            source_text=(parsed_doc.get("raw_text") or file_payload.get("filename", ""))[:300],
            en_name_candidate=f"Connection from {file_payload.get('filename', 'file')}",
            cn_name_candidate="",
            alias_candidates=[],
            description_candidate="auto extracted candidate connection",
            granularity_candidate=granularity,
            connection_modality_candidate="unknown",
            source_region_ref_candidate=src_ref,
            target_region_ref_candidate=tgt_ref,
            confidence=0.55,
            direction_label="bidirectional",
            extraction_method=extraction_method,
            llm_model=llm_model,
            status="pending_review",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        return [row.__dict__.copy()]
