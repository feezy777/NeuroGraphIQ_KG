from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path


def make_id(prefix: str) -> str:
    """Generate a globally unique ID by combining a millisecond timestamp with a UUID4 fragment.

    Using uuid4 instead of a SHA1 of the timestamp ensures that IDs created
    within the same millisecond (e.g. inside a tight parse/chunk loop) are
    always distinct, preventing ON CONFLICT overwrites in PostgreSQL.
    """
    stamp = str(int(time.time() * 1000))
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}_{stamp}_{suffix}"


def _allen_ascii_structure_id(s: str, max_len: int = 96) -> str:
    """Allen/CCF 风格：仅 ASCII 字母数字与下划线；IRI 取末段；无中文或其它非 ASCII 符号。

    参考 Allen Brain Atlas 结构缩写习惯（紧凑、无空格），本体 term_key 常为英文缩写或数字段。
    """
    s = (s or "").strip()
    if not s:
        return ""
    if "/" in s:
        s = s.split("/")[-1]
    if "#" in s:
        s = s.split("#")[-1]
    s = s.replace(":", "_")
    out: list[str] = []
    for ch in s:
        if ch.isascii() and (ch.isalnum() or ch == "_"):
            out.append(ch)
        elif ch.isspace() or ch in "-\u00a0":
            out.append("_")
    seg = "".join(out)
    seg = re.sub(r"_+", "_", seg).strip("_")
    if not seg:
        return ""
    return seg[:max_len]


def _semantic_en_slug_ascii(en: str) -> str:
    """仅从英文名得到 ASCII snake（小写），不含 Unicode 字母。"""
    en = (en or "").strip().lower()
    if not en:
        return ""
    parts: list[str] = []
    for ch in en:
        if "a" <= ch <= "z" or ch.isdigit():
            parts.append(ch)
        elif ch in " \t-_":
            parts.append("_")
    s = "".join(parts)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80] if s else ""


def global_region_id_canonical(
    term_key: str,
    canonical: str,
    en_name: str,
    cn_name: str,
) -> str:
    """跨文件统一的「脑区概念」标识；**仅 ASCII**，不出现中文。

    优先级：ontology term_key（Allen 式缩写段）> canonical 的 ASCII 段 > 英文 snake >
    纯中文名 → CN_ + sha256 短十六进制（稳定、可对接）。
    """
    t = (term_key or "").strip()
    if t:
        a = _allen_ascii_structure_id(t)
        if a:
            return a
    c = (canonical or "").strip()
    if c:
        a = _allen_ascii_structure_id(c)
        if a:
            return a
    e = _semantic_en_slug_ascii(en_name)
    if e:
        return e
    cn = (cn_name or "").strip()
    if cn:
        return "CN_" + hashlib.sha256(cn.encode("utf-8")).hexdigest()[:12]
    return "unknown_region"


def derive_global_region_id_for_row(review_note: str, en_name: str, cn_name: str) -> str:
    """从 review_note 中读取 ontology_binding，与名称一起得到 global_region_id。"""
    term_key = ""
    canonical = ""
    try:
        n = json.loads(review_note or "{}")
        ob = n.get("ontology_binding") or {}
        term_key = str(ob.get("term_key") or "").strip()
        canonical = str(ob.get("canonical") or "").strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return global_region_id_canonical(term_key, canonical, en_name, cn_name)


def normalize_for_candidate_pk_segment(global_region_id: str) -> str:
    """主键 id 中间段：与 Allen 式结构名一致，仅 ASCII，长度收紧。"""
    g = (global_region_id or "").strip()
    if not g:
        return "unknown_region"
    a = _allen_ascii_structure_id(g, max_len=64)
    return a if a else "unknown_region"


def make_region_candidate_id(
    *,
    file_id: str,
    en_name: str,
    cn_name: str,
    source_text: str = "",
    batch_index: int = 0,
    term_key: str = "",
    canonical: str = "",
) -> str:
    """主键 id：Allen 式 ASCII 语义段 + 短指纹（同文件同概念不同证据行）。"""
    g = global_region_id_canonical(term_key, canonical, en_name, cn_name)
    seg = normalize_for_candidate_pk_segment(g)
    basis = "|".join(
        [
            str(file_id or ""),
            g,
            seg,
            str(source_text or ""),
            str(int(batch_index)),
            str(term_key or ""),
            str(en_name or ""),
            str(cn_name or ""),
        ]
    )
    u6 = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:6]
    return f"cr_{seg}_{u6}"


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    p = Path(path)
    if not p.exists():
        return ""
    with p.open("rb") as fh:
        while True:
            chunk = fh.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_type_from_name(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().strip(".")
    return ext or "unknown"
