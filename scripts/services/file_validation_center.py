from __future__ import annotations

import csv
import json
import re
import shutil
import time
import uuid
import zipfile
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from scripts.utils.deepseek_client import DeepSeekClient
from scripts.utils.excel_reader import read_xlsx_rows
from scripts.utils.io_utils import ensure_dir, read_json, read_jsonl, write_json, write_jsonl
from scripts.services.runtime_config import resolve_runtime_deepseek


SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonld": "jsonld",
    ".jsonl": "jsonl",
    ".txt": "txt",
    ".md": "md",
    ".pdf": "pdf",
    ".docx": "docx",
    ".rdf": "rdf",
    ".owl": "owl",
    ".xml": "xml",
}

TABULAR_TYPES = {"xlsx", "csv", "tsv", "jsonl", "json"}
TEXT_TYPES = {"txt", "md", "rdf", "owl", "xml", "pdf", "docx", "jsonld"}

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
SEVERITY_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}


def center_root(root: str | Path) -> Path:
    return ensure_dir(root)


def index_path(root: str | Path) -> Path:
    return center_root(root) / "index.json"


def _root_dirs(root: str | Path) -> dict[str, Path]:
    base = center_root(root)
    return {
        "base": base,
        "original": ensure_dir(base / "original"),
        "normalized": ensure_dir(base / "normalized"),
        "processed": ensure_dir(base / "processed"),
        "reports": ensure_dir(base / "reports"),
    }


def _load_index(root: str | Path) -> dict[str, Any]:
    p = index_path(root)
    if not p.exists():
        return {"files": {}, "order": []}
    data = read_json(p)
    if not isinstance(data, dict):
        return {"files": {}, "order": []}
    data.setdefault("files", {})
    data.setdefault("order", [])
    return data


def _save_index(root: str | Path, data: dict[str, Any]) -> None:
    write_json(index_path(root), data)


def _norm_header(value: str) -> str:
    s = str(value or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "col"


def _normalize_laterality(value: str) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "l": "left",
        "left": "left",
        "左": "left",
        "左侧": "left",
        "左边": "left",
        "r": "right",
        "right": "right",
        "右": "right",
        "右侧": "right",
        "右边": "right",
        "bilateral": "bilateral",
        "both": "bilateral",
        "双侧": "bilateral",
        "两侧": "bilateral",
        "midline": "midline",
        "middle": "midline",
        "中线": "midline",
        "正中": "midline",
    }
    return mapping.get(raw, str(value or "").strip())

def _normalize_text(value: str) -> str:
    text = str(value or "")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    deduped = 0
    for row in rows:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        out.append(row)
    return out, deduped


def _read_text_best_effort(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def _read_csv_rows(path: Path, delimiter: str) -> list[dict[str, Any]]:
    text = _read_text_best_effort(path)
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    rows: list[dict[str, Any]] = []
    for row in reader:
        cleaned: dict[str, Any] = {}
        for k, v in (row or {}).items():
            if k is None:
                continue
            cleaned[str(k)] = "" if v is None else str(v)
        if any(str(v).strip() for v in cleaned.values()):
            rows.append(cleaned)
    return rows


def _read_json_rows(path: Path) -> tuple[str, Any]:
    data = read_json(path)
    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return "table", [dict(item) for item in data]
        return "json", data
    if isinstance(data, dict):
        return "json", data
    return "json", {"value": data}


def _read_pdf_text(path: Path) -> str:
    data = path.read_bytes()
    text = data.decode("latin-1", errors="ignore")
    literals = re.findall(r"\(([^()]*)\)", text)
    cleaned = "\n".join(piece for piece in literals if len(piece.strip()) >= 3)
    if len(cleaned) >= 120:
        return cleaned
    fallback_chunks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\s,.;:()]{4,}", text)
    return "\n".join(chunk.strip() for chunk in fallback_chunks[:1000])


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        root = ET.fromstring(zf.read("word/document.xml"))
        texts: list[str] = []
        for node in root.findall(".//w:t", WORD_NS):
            if node.text:
                texts.append(node.text)
        return "\n".join(texts)


def _parse_original(record: dict[str, Any]) -> dict[str, Any]:
    file_type = str(record.get("file_type", "")).lower()
    path = Path(str(record.get("original_path", "")))
    if not path.exists():
        raise FileNotFoundError(f"Original file not found: {path}")

    if file_type == "xlsx":
        rows = read_xlsx_rows(path, sheet_index=1, header_row=1)
        return {"kind": "table", "rows": rows}
    if file_type == "csv":
        return {"kind": "table", "rows": _read_csv_rows(path, delimiter=",")}
    if file_type == "tsv":
        return {"kind": "table", "rows": _read_csv_rows(path, delimiter="\t")}
    if file_type == "jsonl":
        return {"kind": "table", "rows": read_jsonl(path)}
    if file_type == "json":
        kind, value = _read_json_rows(path)
        if kind == "table":
            return {"kind": "table", "rows": value}
        return {"kind": "json", "value": value}
    if file_type == "jsonld":
        # Keep jsonld as text for ontology/context-aware validation.
        return {"kind": "text", "text": _read_text_best_effort(path)}
    if file_type in {"txt", "md", "rdf", "owl", "xml"}:
        return {"kind": "text", "text": _read_text_best_effort(path)}
    if file_type == "pdf":
        return {"kind": "text", "text": _read_pdf_text(path)}
    if file_type == "docx":
        return {"kind": "text", "text": _read_docx_text(path)}
    raise ValueError(f"Unsupported file type: {file_type}")


def _normalize_parsed(file_type: str, parsed: dict[str, Any]) -> dict[str, Any]:
    change_log: list[str] = []
    kind = parsed.get("kind")
    if kind == "table":
        rows = parsed.get("rows") or []
        if not isinstance(rows, list):
            rows = []
        input_rows = len(rows)
        normalized_rows: list[dict[str, Any]] = []
        header_mapping: dict[str, str] = {}
        used_headers: dict[str, int] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            out: dict[str, Any] = {}
            for key, value in row.items():
                src_key = str(key or "").strip()
                if src_key not in header_mapping:
                    candidate = _norm_header(src_key)
                    idx = used_headers.get(candidate, 0)
                    used_headers[candidate] = idx + 1
                    final = candidate if idx == 0 else f"{candidate}_{idx + 1}"
                    header_mapping[src_key] = final
                    if final != src_key:
                        change_log.append(f"header_map:{src_key}->{final}")
                target_key = header_mapping[src_key]
                if isinstance(value, str):
                    out_val: Any = value.strip()
                else:
                    out_val = value
                if "laterality" in target_key or "hemisphere" in target_key:
                    out_val = _normalize_laterality(str(out_val))
                out[target_key] = out_val
            if any(str(v).strip() for v in out.values()):
                normalized_rows.append(out)

        deduped_rows, deduped_count = _dedupe_rows(normalized_rows)
        if deduped_count:
            change_log.append(f"dedupe_exact_rows:{deduped_count}")
        return {
            "kind": "table",
            "rows": deduped_rows,
            "stats": {
                "input_rows": input_rows,
                "output_rows": len(deduped_rows),
                "deduped_rows": deduped_count,
            },
            "change_log": sorted(set(change_log)),
        }

    if kind == "json":
        value = parsed.get("value")
        return {
            "kind": "json",
            "value": value,
            "stats": {"items": len(value) if isinstance(value, list) else 1},
            "change_log": [],
        }

    text = _normalize_text(str(parsed.get("text") or ""))
    if file_type in {"rdf", "owl", "xml"}:
        lines: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.lower().startswith("@prefix") or stripped.lower().startswith("prefix"):
                stripped = re.sub(r"\s+", " ", stripped)
            lines.append(stripped)
        text = "\n".join(lines)
        change_log.append("normalized_prefix_namespace_lines")

    change_log.append("normalized_line_endings")
    return {
        "kind": "text",
        "text": text,
        "stats": {"chars": len(text), "lines": len(text.splitlines())},
        "change_log": sorted(set(change_log)),
    }


def _normalized_artifact_path(root: str | Path, file_id: str) -> Path:
    return _root_dirs(root)["normalized"] / f"{file_id}.normalized.json"


def _processed_artifact_path(root: str | Path, file_id: str, kind: str) -> Path:
    processed = _root_dirs(root)["processed"]
    if kind == "table":
        return processed / f"{file_id}.processed.jsonl"
    if kind == "json":
        return processed / f"{file_id}.processed.json"
    return processed / f"{file_id}.processed.txt"


def _report_path(root: str | Path, file_id: str) -> Path:
    return _root_dirs(root)["reports"] / f"{file_id}.report.json"


def _severity(label: str) -> int:
    return SEVERITY_ORDER.get(str(label or "").upper(), 1)


def _normalize_label(label: str, score: float) -> str:
    raw = str(label or "").strip().upper()
    if raw in {"PASS", "WARN", "FAIL"}:
        return raw
    if score >= 85:
        return "PASS"
    if score >= 65:
        return "WARN"
    return "FAIL"


def _build_deepseek_input(file_id: str, file_type: str, normalized: dict[str, Any], mode: str) -> dict[str, Any]:
    kind = normalized.get("kind")
    if kind == "table":
        rows = normalized.get("rows") or []
        sample = rows[:120] if mode == "sample" else rows
        return {
            "file_id": file_id,
            "file_type": file_type,
            "kind": "table",
            "stats": normalized.get("stats", {}),
            "headers": list(sample[0].keys()) if sample else [],
            "sample_rows": sample[:300],
        }
    if kind == "json":
        value = normalized.get("value")
        text = json.dumps(value, ensure_ascii=False)[:60000]
        return {
            "file_id": file_id,
            "file_type": file_type,
            "kind": "json",
            "stats": normalized.get("stats", {}),
            "sample_json": text,
        }
    text = str(normalized.get("text") or "")
    if mode == "sample":
        text = text[:18000]
    else:
        text = text[:60000]
    return {
        "file_id": file_id,
        "file_type": file_type,
        "kind": "text",
        "stats": normalized.get("stats", {}),
        "sample_text": text,
    }


def _local_checks(file_type: str, normalized: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    kind = normalized.get("kind")
    if kind == "table":
        rows = normalized.get("rows") or []
        if not rows:
            issues.append({"severity": "FAIL", "code": "empty_rows", "message": "No valid rows after normalization."})
        else:
            headers = list(rows[0].keys())
            if not headers:
                issues.append({"severity": "FAIL", "code": "empty_headers", "message": "No headers detected."})
            empty_ratio = 0.0
            values = 0
            empties = 0
            for row in rows:
                for value in row.values():
                    values += 1
                    if str(value or "").strip() == "":
                        empties += 1
            if values:
                empty_ratio = empties / values
            if empty_ratio > 0.4:
                issues.append(
                    {
                        "severity": "WARN",
                        "code": "high_empty_ratio",
                        "message": f"High empty ratio: {empty_ratio:.2%}",
                    }
                )
    elif kind == "text":
        text = str(normalized.get("text") or "")
        if not text.strip():
            issues.append({"severity": "FAIL", "code": "empty_text", "message": "Text content is empty."})
        elif len(text) < 20:
            issues.append({"severity": "WARN", "code": "very_short_text", "message": "Text content is very short."})
    elif kind == "json":
        value = normalized.get("value")
        if value is None:
            issues.append({"severity": "FAIL", "code": "empty_json", "message": "JSON value is empty."})
    else:
        issues.append({"severity": "WARN", "code": "unknown_kind", "message": f"Unknown normalized kind: {kind}"})

    if file_type not in set(SUPPORTED_EXTENSIONS.values()):
        issues.append({"severity": "WARN", "code": "unsupported_type_hint", "message": f"Unknown type: {file_type}"})
    return issues


def _call_deepseek(runtime: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    override_cfg = runtime.get("_task_deepseek_override")
    resolved_runtime, resolved_meta = resolve_runtime_deepseek(runtime, override_cfg if isinstance(override_cfg, dict) else None)
    requested_use_deepseek = bool(resolved_runtime.get("pipeline", {}).get("use_deepseek", True))
    deepseek_cfg = resolved_runtime.get("deepseek", {}) if isinstance(resolved_runtime.get("deepseek"), dict) else {}
    has_deepseek_key = bool(str(deepseek_cfg.get("api_key", "")).strip())
    effective_use_deepseek = requested_use_deepseek and has_deepseek_key
    base = {
        "requested_use_deepseek": requested_use_deepseek,
        "effective_use_deepseek": effective_use_deepseek,
        "status": "skipped",
        "reason": "",
        "result": {},
        "config_source": str(resolved_meta.get("source", "global")),
        "request_sent": False,
        "response_received": False,
        "http_status": None,
        "request_target": "",
        "model": "",
        "elapsed_ms": 0,
    }
    file_id = str(payload.get("file_id", "") or "")
    print(f"[CHECK] start file_id={file_id}")
    print(
        f"[CHECK] deepseek config source={resolved_meta.get('source', 'global')} "
        f"model={deepseek_cfg.get('model', '')} baseUrl={deepseek_cfg.get('base_url', '')}"
    )
    if not requested_use_deepseek:
        base["reason"] = "deepseek_disabled_by_config"
        print(f"[CHECK] deepseek disabled file_id={file_id}")
        return base
    if not has_deepseek_key:
        raise RuntimeError("DEEPSEEK_API_KEY is empty.")

    system_prompt = (
        "You are a strict data quality and schema validation engine. "
        "Return JSON only and do not include markdown fences."
    )
    user_prompt = (
        "Validate this dataset payload for downstream KG extraction.\n"
        "Return JSON keys exactly:\n"
        "- overall_label: PASS|WARN|FAIL\n"
        "- score: 0..100 number\n"
        "- summary_cn: short Chinese summary\n"
        "- issues: [{severity, code, message, suggestion}]\n"
        "- auto_fix_plan: [{action, reason, risk}]\n"
        "- manual_fix_plan: [{action, reason, priority}]\n"
        "- chunk_recommended: boolean\n"
        "- chunk_reason: string\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    started = time.perf_counter()
    try:
        client = DeepSeekClient(
            base_url=str(deepseek_cfg.get("base_url", "")).strip() or None,
            model=str(deepseek_cfg.get("model", "")).strip() or None,
            api_key=str(deepseek_cfg.get("api_key", "")).strip() or None,
        )
        target = f"{client.base_url}/chat/completions"
        base["request_target"] = target
        base["model"] = str(client.model or "")
        print(f"[CHECK] calling deepseek... file_id={file_id} endpoint={target} model={client.model}")
        print(f"[CHECK] request -> deepseek file_id={file_id} target={target}")
        base["request_sent"] = True
        result, status_code = client.chat_json_with_status(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=2200,
        )
        base["response_received"] = True
        base["http_status"] = int(status_code)
        base["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        print(f"[CHECK] response status={status_code} file_id={file_id}")
        if not isinstance(result, dict):
            raise ValueError("DeepSeek validation response must be a JSON object.")
        if "overall_label" not in result or "score" not in result:
            raise ValueError("DeepSeek validation response missing required fields: overall_label/score.")
        print(f"[CHECK] deepseek response received file_id={file_id}")
        print(f"[CHECK] success file_id={file_id} elapsed_ms={base['elapsed_ms']}")
    except Exception as exc:
        if base.get("elapsed_ms", 0) <= 0:
            base["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        if hasattr(exc, "code") and base.get("http_status") is None:
            try:
                base["http_status"] = int(getattr(exc, "code"))
            except Exception:
                base["http_status"] = None
        base["reason"] = str(exc)
        print(f"[CHECK] deepseek error file_id={file_id} reason={exc}")
        print(f"[CHECK] failed file_id={file_id}")
        raise
    base["status"] = "ok"
    base["result"] = result
    return base


def _merge_unique_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _chunk_payloads(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    kind = normalized.get("kind")
    payloads: list[dict[str, Any]] = []
    if kind == "table":
        rows = normalized.get("rows") or []
        chunk_size = 300
        for idx in range(0, len(rows), chunk_size):
            chunk_rows = rows[idx : idx + chunk_size]
            payloads.append(
                {
                    "kind": "table",
                    "chunk_index": (idx // chunk_size) + 1,
                    "chunk_size": len(chunk_rows),
                    "headers": list(chunk_rows[0].keys()) if chunk_rows else [],
                    "sample_rows": chunk_rows,
                }
            )
        return payloads[:8]
    if kind == "text":
        text = str(normalized.get("text") or "")
        chunk_size = 15000
        for idx in range(0, len(text), chunk_size):
            payloads.append(
                {
                    "kind": "text",
                    "chunk_index": (idx // chunk_size) + 1,
                    "sample_text": text[idx : idx + chunk_size],
                }
            )
        return payloads[:8]
    return payloads


def _build_report(
    file_id: str,
    file_type: str,
    normalized: dict[str, Any],
    local_issues: list[dict[str, Any]],
    llm_initial: dict[str, Any],
    llm_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    llm_result = llm_initial.get("result", {}) if isinstance(llm_initial, dict) else {}
    llm_status = str(llm_initial.get("status", ""))
    llm_ok = llm_status == "ok" and isinstance(llm_result, dict) and bool(llm_result)
    has_local_fail = any(str(item.get("severity", "")).upper() == "FAIL" for item in local_issues)
    has_local_warn = any(str(item.get("severity", "")).upper() == "WARN" for item in local_issues)

    if llm_ok:
        score = float(llm_result.get("score", 0) or 0)
        label = _normalize_label(str(llm_result.get("overall_label", "")), score)
    else:
        # DeepSeek skipped/unavailable should not automatically become FAIL.
        if has_local_fail:
            score = 45.0
            label = "FAIL"
        elif has_local_warn:
            score = 72.0
            label = "WARN"
        else:
            score = 88.0
            label = "PASS"

    issues = _merge_unique_dicts(local_issues + list(llm_result.get("issues", []) or []))
    auto_fix_plan = _merge_unique_dicts(list(llm_result.get("auto_fix_plan", []) or []))
    manual_fix_plan = _merge_unique_dicts(list(llm_result.get("manual_fix_plan", []) or []))
    summary_cn = str(llm_result.get("summary_cn", "") or "")
    if not summary_cn and not llm_ok:
        reason = str(llm_initial.get("reason", "") or "").strip()
        summary_cn = (
            f"DeepSeek未执行或不可用；当前标注基于本地规则。{reason}"
            if reason
            else "DeepSeek未执行或不可用；当前标注基于本地规则。"
        )
    chunk_reports: list[dict[str, Any]] = []
    if llm_chunks:
        chunk_scores: list[float] = [score]
        worst_label = label
        for chunk in llm_chunks:
            chunk_result = chunk.get("result", {}) if isinstance(chunk, dict) else {}
            chunk_score = float(chunk_result.get("score", 0) or 0)
            chunk_label = _normalize_label(str(chunk_result.get("overall_label", "")), chunk_score)
            chunk_scores.append(chunk_score)
            if _severity(chunk_label) > _severity(worst_label):
                worst_label = chunk_label
            issues = _merge_unique_dicts(issues + list(chunk_result.get("issues", []) or []))
            auto_fix_plan = _merge_unique_dicts(auto_fix_plan + list(chunk_result.get("auto_fix_plan", []) or []))
            manual_fix_plan = _merge_unique_dicts(manual_fix_plan + list(chunk_result.get("manual_fix_plan", []) or []))
            chunk_reports.append(
                {
                    "status": chunk.get("status", ""),
                    "reason": chunk.get("reason", ""),
                    "result": chunk_result,
                }
            )
        score = min(chunk_scores) if chunk_scores else score
        label = worst_label

    if has_local_fail:
        label = "FAIL"
    if label not in {"PASS", "WARN", "FAIL"}:
        label = "WARN"

    if not auto_fix_plan:
        auto_fix_plan = [{"action": "normalize_whitespace_and_dedupe", "reason": "low_risk_default", "risk": "low"}]
    manual_required_count = len([x for x in issues if str(x.get("severity", "")).upper() in {"WARN", "FAIL"}])
    blocked_on_load = label == "FAIL"

    return {
        "file_id": file_id,
        "file_type": file_type,
        "overall_label": label,
        "score": int(round(score)),
        "issues": issues,
        "auto_fix_plan": auto_fix_plan,
        "manual_fix_plan": manual_fix_plan,
        "summary_cn": summary_cn,
        "gate_decision": {
            "allow_preview": True,
            "allow_extract": True,
            "allow_load": not blocked_on_load,
            "block_reason": "validation_fail" if blocked_on_load else "",
        },
        "auto_applied_count": 0,
        "manual_required_count": manual_required_count,
        "blocked_on_load": blocked_on_load,
        "validation_trace": {
            "local_issue_count": len(local_issues),
            "llm_initial": {
                "status": llm_initial.get("status", ""),
                "reason": llm_initial.get("reason", ""),
                "requested_use_deepseek": llm_initial.get("requested_use_deepseek", False),
                "effective_use_deepseek": llm_initial.get("effective_use_deepseek", False),
                "config_source": llm_initial.get("config_source", "global"),
                "request_sent": llm_initial.get("request_sent", False),
                "response_received": llm_initial.get("response_received", False),
                "http_status": llm_initial.get("http_status"),
                "request_target": llm_initial.get("request_target", ""),
                "model": llm_initial.get("model", ""),
                "elapsed_ms": llm_initial.get("elapsed_ms", 0),
            },
            "chunk_count": len(chunk_reports),
            "chunk_reports": chunk_reports,
        },
        "normalized_stats": normalized.get("stats", {}),
        "normalized_change_log": normalized.get("change_log", []),
    }


def _should_chunk_validate(normalized: dict[str, Any], llm_initial: dict[str, Any]) -> bool:
    result = llm_initial.get("result", {}) if isinstance(llm_initial, dict) else {}
    initial_score = float(result.get("score", 100) or 100)
    chunk_recommended = bool(result.get("chunk_recommended", False))
    manual_fix = list(result.get("manual_fix_plan", []) or [])
    kind = normalized.get("kind")
    if kind == "table":
        rows = normalized.get("rows") or []
        large = len(rows) > 500
    elif kind == "text":
        large = len(str(normalized.get("text") or "")) > 20000
    else:
        large = False
    return large and (chunk_recommended or initial_score < 80 or len(manual_fix) > 0)


def _write_normalized_artifact(root: str | Path, file_id: str, normalized: dict[str, Any]) -> Path:
    path = _normalized_artifact_path(root, file_id)
    write_json(path, normalized)
    return path


def _load_normalized_artifact(root: str | Path, file_id: str) -> dict[str, Any]:
    path = _normalized_artifact_path(root, file_id)
    if not path.exists():
        raise FileNotFoundError(f"Normalized artifact missing for {file_id}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid normalized artifact for {file_id}")
    return data


def _public_record(record: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(record)
    if report:
        out.update(
            {
                "overall_label": report.get("overall_label"),
                "score": report.get("score"),
                "blocked_on_load": report.get("blocked_on_load", False),
                "manual_required_count": report.get("manual_required_count", 0),
                "auto_applied_count": report.get("auto_applied_count", 0),
                "summary_cn": report.get("summary_cn", ""),
            }
        )
    return out


def _build_file_record(
    *,
    file_id: str,
    filename: str,
    ext: str,
    file_type: str,
    target: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {
        "file_id": file_id,
        "filename": filename,
        "extension": ext,
        "file_type": file_type,
        "uploaded_at": now,
        "status": "uploaded",
        "size_bytes": target.stat().st_size,
        "original_path": str(target),
        "normalized_path": "",
        "processed_path": "",
        "report_path": "",
        "blocked_on_load": False,
        "last_validation_at": "",
        "last_processed_at": "",
    }
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if key in {"file_id", "original_path", "size_bytes", "uploaded_at"}:
                continue
            record[key] = value
    return record


def _register_file_from_path(
    *,
    source_path: Path,
    filename: str,
    root: str | Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dirs = _root_dirs(root)
    if not filename.strip():
        raise ValueError("file_missing")
    ext = Path(filename).suffix.lower()
    file_type = SUPPORTED_EXTENSIONS.get(ext)
    if not file_type:
        raise ValueError(f"unsupported_file_extension:{ext}")

    file_id = f"file_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    target = dirs["original"] / f"{file_id}_{filename}"
    shutil.copy2(source_path, target)

    index = _load_index(root)
    record = _build_file_record(
        file_id=file_id,
        filename=filename,
        ext=ext,
        file_type=file_type,
        target=target,
        metadata=metadata,
    )
    index["files"][file_id] = record
    index["order"] = [file_id] + [x for x in index.get("order", []) if x != file_id]
    _save_index(root, index)
    return record


def register_uploaded_file(
    file_storage: Any,
    root: str | Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filename = Path(str(getattr(file_storage, "filename", "") or "")).name
    if not filename:
        raise ValueError("file_missing")
    temp_source = _root_dirs(root)["base"] / f".tmp_upload_{uuid.uuid4().hex}_{filename}"
    file_storage.save(temp_source)
    try:
        return _register_file_from_path(
            source_path=temp_source,
            filename=filename,
            root=root,
            metadata=metadata,
        )
    finally:
        if temp_source.exists():
            temp_source.unlink(missing_ok=True)


def register_local_file_path(
    local_path: str | Path,
    root: str | Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(local_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"local_file_not_found:{source}")
    return _register_file_from_path(
        source_path=source,
        filename=source.name,
        root=root,
        metadata=metadata,
    )


def list_files(root: str | Path) -> dict[str, Any]:
    index = _load_index(root)
    files: list[dict[str, Any]] = []
    for file_id in index.get("order", []):
        rec = index.get("files", {}).get(file_id)
        if not rec:
            continue
        report = None
        report_path_value = str(rec.get("report_path") or "")
        if report_path_value and Path(report_path_value).exists():
            try:
                report = read_json(report_path_value)
            except Exception:
                report = None
        files.append(_public_record(rec, report))

    stats = {
        "total": len(files),
        "validated": len([x for x in files if x.get("overall_label")]),
        "fail": len([x for x in files if x.get("overall_label") == "FAIL"]),
        "warn": len([x for x in files if x.get("overall_label") == "WARN"]),
        "pass": len([x for x in files if x.get("overall_label") == "PASS"]),
    }
    return {"files": files, "stats": stats}


def _get_record(root: str | Path, file_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    index = _load_index(root)
    rec = index.get("files", {}).get(file_id)
    if not rec:
        raise KeyError(f"file_not_found:{file_id}")
    return index, rec


def validate_file(file_id: str, runtime: dict[str, Any], root: str | Path) -> dict[str, Any]:
    index, rec = _get_record(root, file_id)
    file_type = str(rec.get("file_type", "")).lower()
    rec["status"] = "validating"
    index["files"][file_id] = rec
    _save_index(root, index)

    try:
        parsed = _parse_original(rec)
        normalized = _normalize_parsed(file_type=file_type, parsed=parsed)
        normalized_path = _write_normalized_artifact(root, file_id, normalized)

        local_issues = _local_checks(file_type=file_type, normalized=normalized)
        sample_payload = _build_deepseek_input(file_id=file_id, file_type=file_type, normalized=normalized, mode="sample")
        llm_initial = _call_deepseek(runtime=runtime, payload=sample_payload)

        llm_chunks: list[dict[str, Any]] = []
        if _should_chunk_validate(normalized, llm_initial):
            for chunk_payload in _chunk_payloads(normalized):
                payload = {
                    "file_id": file_id,
                    "file_type": file_type,
                    "chunk_mode": True,
                    **chunk_payload,
                }
                llm_chunks.append(_call_deepseek(runtime=runtime, payload=payload))

        report = _build_report(
            file_id=file_id,
            file_type=file_type,
            normalized=normalized,
            local_issues=local_issues,
            llm_initial=llm_initial,
            llm_chunks=llm_chunks,
        )
        report["validated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["normalized_path"] = str(normalized_path)
        report_path_value = _report_path(root, file_id)
        write_json(report_path_value, report)

        rec["normalized_path"] = str(normalized_path)
        rec["report_path"] = str(report_path_value)
        rec["status"] = "validated"
        rec["blocked_on_load"] = bool(report.get("blocked_on_load", False))
        rec["last_validation_at"] = report["validated_at"]
        rec.pop("last_validation_error", None)
        index["files"][file_id] = rec
        _save_index(root, index)
        return report
    except Exception as exc:
        rec["status"] = "validation_failed"
        rec["last_validation_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["last_validation_error"] = str(exc)
        index["files"][file_id] = rec
        _save_index(root, index)
        raise


def apply_auto_fix(file_id: str, root: str | Path) -> dict[str, Any]:
    index, rec = _get_record(root, file_id)
    report_path_value = str(rec.get("report_path") or "")
    report = read_json(report_path_value) if report_path_value and Path(report_path_value).exists() else {}

    normalized = _load_normalized_artifact(root, file_id)
    kind = str(normalized.get("kind") or "text")
    processed_path = _processed_artifact_path(root, file_id, kind)

    if kind == "table":
        rows = normalized.get("rows") or []
        write_jsonl(processed_path, rows)
        auto_applied = len(normalized.get("change_log", []) or [])
    elif kind == "json":
        write_json(processed_path, normalized.get("value"))
        auto_applied = len(normalized.get("change_log", []) or [])
    else:
        processed_path.write_text(str(normalized.get("text") or ""), encoding="utf-8")
        auto_applied = len(normalized.get("change_log", []) or [])

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec["processed_path"] = str(processed_path)
    rec["status"] = "processed"
    rec["last_processed_at"] = now
    index["files"][file_id] = rec

    if isinstance(report, dict) and report:
        report["auto_applied_count"] = auto_applied
        report["manual_required_count"] = len(report.get("manual_fix_plan", []) or [])
        report["processed_path"] = str(processed_path)
        report["processed_at"] = now
        write_json(_report_path(root, file_id), report)

    _save_index(root, index)
    return {
        "file_id": file_id,
        "processed_path": str(processed_path),
        "change_log": normalized.get("change_log", []),
        "auto_applied_count": auto_applied,
    }


def get_file_report(file_id: str, root: str | Path) -> dict[str, Any]:
    _, rec = _get_record(root, file_id)
    report_path_value = str(rec.get("report_path") or "")
    report = read_json(report_path_value) if report_path_value and Path(report_path_value).exists() else {}
    preview = get_file_preview(file_id=file_id, root=root, page=1, page_size=200, view="auto")
    return {"file": _public_record(rec, report if isinstance(report, dict) else None), "report": report, "preview": preview}


def _normalized_for_preview(file_id: str, root: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    index, rec = _get_record(root, file_id)
    normalized_path_value = str(rec.get("normalized_path") or "")
    if normalized_path_value and Path(normalized_path_value).exists():
        normalized = read_json(normalized_path_value)
        if isinstance(normalized, dict):
            return normalized, rec

    parsed = _parse_original(rec)
    normalized = _normalize_parsed(file_type=str(rec.get("file_type") or ""), parsed=parsed)
    normalized_path = _write_normalized_artifact(root, file_id, normalized)
    rec["normalized_path"] = str(normalized_path)
    index["files"][file_id] = rec
    _save_index(root, index)
    return normalized, rec


def get_file_preview(
    file_id: str,
    root: str | Path,
    page: int = 1,
    page_size: int = 120,
    view: str = "auto",
) -> dict[str, Any]:
    normalized, rec = _normalized_for_preview(file_id=file_id, root=root)
    kind = str(normalized.get("kind") or "")
    file_type = str(rec.get("file_type") or "").lower()
    page = max(1, int(page))
    page_size = max(1, min(2000, int(page_size)))
    view_mode = str(view or "auto").strip().lower()

    if kind == "table":
        rows = normalized.get("rows") or []
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "mode": "table",
            "file_id": file_id,
            "file_type": file_type,
            "page": page,
            "page_size": page_size,
            "total_rows": total,
            "total_pages": total_pages,
            "headers": list(rows[0].keys()) if rows else [],
            "rows": rows[start:end],
        }

    if kind == "json":
        return {
            "mode": "json",
            "file_id": file_id,
            "file_type": file_type,
            "value": normalized.get("value"),
            "page": 1,
            "page_size": 1,
            "total_pages": 1,
        }

    if file_type in {"pdf", "docx"} and view_mode in {"auto", "raw", "embed"}:
        content_info = get_file_content(file_id=file_id, root=root)
        if content_info.get("exists"):
            return {
                "mode": "raw_embed",
                "file_id": file_id,
                "file_type": file_type,
                "content_url": f"/api/files/{file_id}/content",
                "mime_type": content_info.get("mime_type"),
                "fallback_reason": "",
            }
        view_mode = "text"

    text = str(normalized.get("text") or "")
    lines = text.splitlines() if text else []
    if not lines:
        lines = [text] if text else []
    total_lines = len(lines)
    total_pages = max(1, (total_lines + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "mode": "text",
        "file_id": file_id,
        "file_type": file_type,
        "page": page,
        "page_size": page_size,
        "total_lines": total_lines,
        "total_pages": total_pages,
        "text": "\n".join(lines[start:end]),
        "chars": len(text),
    }


def get_file_content(file_id: str, root: str | Path) -> dict[str, Any]:
    _, rec = _get_record(root, file_id)
    path = Path(str(rec.get("original_path") or ""))
    exists = path.exists()
    mime_type = ""
    if exists:
        mime_type = guess_type(str(path))[0] or "application/octet-stream"
    return {
        "file_id": file_id,
        "path": str(path),
        "exists": exists,
        "mime_type": mime_type,
        "file_type": str(rec.get("file_type") or ""),
        "filename": str(rec.get("filename") or path.name),
    }


def remove_file(file_id: str, root: str | Path) -> dict[str, Any]:
    index, rec = _get_record(root, file_id)
    removed_paths: list[str] = []
    for field in ("original_path", "normalized_path", "processed_path", "report_path"):
        p = Path(str(rec.get(field) or ""))
        if p.exists() and p.is_file():
            p.unlink(missing_ok=True)
            removed_paths.append(str(p))

    index["files"].pop(file_id, None)
    index["order"] = [x for x in index.get("order", []) if x != file_id]
    _save_index(root, index)
    return {
        "file_id": file_id,
        "filename": str(rec.get("filename") or ""),
        "removed": True,
        "removed_paths": removed_paths,
    }


def blocking_files_for_load(root: str | Path) -> list[dict[str, Any]]:
    listed = list_files(root).get("files", [])
    blocked = [item for item in listed if bool(item.get("blocked_on_load", False))]
    return blocked



