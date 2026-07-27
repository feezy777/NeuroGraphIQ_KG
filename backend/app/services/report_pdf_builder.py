"""Report PDF Builder — A4 layout, blue theme, PNG graph support, proper CJK.

Fixes:
- Inline rich text via write() (no per-fragment multi_cell overlap)
- List/numbered items as single-flow paragraphs
- Graph image placed with explicit Y advance + aspect ratio
- Normalize spaced circuit names / merge orphan numbered lines / avoid line-leading punctuation
"""
from __future__ import annotations

import base64
import io
import os
import re
import tempfile
from datetime import datetime, timezone

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
FONT_PATH_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
ML, MR, MT, MB = 18, 18, 18, 20
PW = 210 - ML - MR
LH = 6.2
BLUE = (22, 119, 255)
BLUE_LIGHT = (240, 245, 255)
GRAY = (100, 100, 100)
COMBINED = (45, 45, 45)
GRAPH_MAX_H = 105  # mm

# Characters that must not start a wrapped line / paragraph (CJK 尾禁则)
_NO_LINE_START = set("。，、；：！？‥…》」』）)]%}‰℃,.;:!?\'\"’”•·")
_NO_LINE_END = set("（《「『([{“‘")
# Leading junk only — do NOT include 【】 here (section markers)
_LEADING_PUNCT_RE = re.compile(
    r"^[。，、；：！？‥…》」』\)\]）)\}%‰℃,.;:!?\'\"’”•·\-\–\—\*\#\|\s]+"
)


def _strip_leading_punct(text: str) -> str:
    """Remove punctuation wrongly placed before the first real character."""
    if not text:
        return text
    prev = None
    while text and text != prev:
        prev = text
        text = _LEADING_PUNCT_RE.sub("", text)
    return text


def _is_section_line(text: str) -> bool:
    s = (text or "").strip()
    return bool(re.match(r"^【.+?】", s)) or s.startswith("## ")


def _is_list_line(text: str) -> bool:
    s = (text or "").strip()
    return bool(re.match(r"^[-•*]\s+", s)) or bool(re.match(r"^\d+[.)、．]\s+", s))


def _collapse_spaces(text: str) -> str:
    """Fix spaced-out names like '海 马 体' / 'PFC   Circuit' while keeping normal word gaps."""
    if not text:
        return text
    # Collapse runs of whitespace to a single space
    text = re.sub(r"[ \t\u00a0\u3000]+", " ", text)
    # Remove spaces between CJK characters: 帕 佩 兹 → 帕佩兹
    text = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", text)
    # Remove spaces around CJK dashes/connectors inside names
    text = re.sub(r"\s*([·\-–—/→])\s*", r"\1", text)
    # Tighten Latin letter-spaced tokens: P F C → PFC (only single-letter runs)
    text = re.sub(
        r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b",
        lambda m: m.group(0).replace(" ", ""),
        text,
    )
    return text.strip()


def _wrap_cjk(pdf: FPDF, text: str, width: float) -> list[str]:
    """Wrap text for multi_cell without letting punctuation start a new line."""
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if pdf.get_string_width(trial) <= width:
            current = trial
            continue
        if not current:
            lines.append(ch)
            current = ""
            continue
        # If new char is punctuation, keep pulling it onto current line when possible
        if ch in _NO_LINE_START:
            current += ch
            # If overflow is tiny, still accept; else force break after punct
            if pdf.get_string_width(current) > width * 1.08 and len(current) > 1:
                lines.append(current[:-1])
                current = current[-1]
            continue
        # Avoid ending previous line with opening brackets
        while current and current[-1] in _NO_LINE_END and len(current) > 1:
            ch = current[-1] + ch
            current = current[:-1]
        lines.append(current)
        current = ch
    if current:
        lines.append(current)
    # Final guard: never let a wrapped line start with punctuation
    fixed: list[str] = []
    for ln in lines:
        while ln and ln[0] in _NO_LINE_START:
            if fixed:
                fixed[-1] += ln[0]
                ln = ln[1:]
            else:
                ln = ln[1:]
        if ln:
            fixed.append(ln)
    return fixed or [""]


def _normalize_markdown(md: str) -> str:
    """Clean LLM markdown artifacts before PDF layout."""
    md = (md or "").replace("\r\n", "\n").replace("\r", "\n")
    md = re.sub(r"^[-*_]{3,}\s*$", "", md, flags=re.MULTILINE)
    md = re.sub(r"^\s*---+\s*$", "", md, flags=re.MULTILINE)
    md = md.replace("\\*\\*\\*", "").replace("\\*\\*", "")
    md = re.sub(r"\.{4,}", "…", md)
    # Park valid bold, strip orphan *, drop snake_case technical ids / stray 】
    bold_hold: list[str] = []

    def _park_bold(m: re.Match[str]) -> str:
        bold_hold.append(m.group(1))
        return f"\x01B{len(bold_hold) - 1}\x01"

    md = re.sub(r"\*{3}(.+?)\*{3}", _park_bold, md)
    md = re.sub(r"\*{2}(.+?)\*{2}", _park_bold, md)
    md = re.sub(r"\*{1,3}", "", md)
    md = re.sub(r"（[a-z][a-z0-9_]{2,}）", "", md)
    md = re.sub(r"\([a-z][a-z0-9_]{2,}\)", "", md)
    md = re.sub(r"（\s*）", "", md)
    md = re.sub(r"\(\s*\)", "", md)
    # Strip orphan 】 outside section header lines
    md = "\n".join(
        ln if re.match(r"^\s*【.+】", ln) else ln.replace("】", "")
        for ln in md.split("\n")
    )

    def _restore_bold(m: re.Match[str]) -> str:
        return f"**{bold_hold[int(m.group(1))]}**"

    md = re.sub(r"\x01B(\d+)\x01", _restore_bold, md)

    raw_lines = md.split("\n")
    merged: list[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].rstrip()
        stripped = line.strip()

        # Bare numbered marker "2." / "3." → pull following content onto same line
        m_bare = re.match(r"^(\d+)\.\s*$", stripped)
        if m_bare:
            j = i + 1
            while j < len(raw_lines) and not raw_lines[j].strip():
                j += 1
            if j < len(raw_lines):
                nxt = raw_lines[j].strip()
                if nxt and not re.match(r"^【.+】$", nxt) and not nxt.startswith("## "):
                    if re.match(r"^(\d+)\.\s+", nxt) or nxt.startswith(("- ", "• ")):
                        merged.append(stripped)
                        i += 1
                        continue
                    merged.append(f"{m_bare.group(1)}. {nxt}")
                    i = j + 1
                    continue
            i += 1
            continue

        # Line that starts with punctuation → append to previous paragraph
        # (never merge into a section header / list line)
        if (
            stripped
            and stripped[0] in _NO_LINE_START
            and not _is_list_line(stripped)
            and merged
            and merged[-1].strip()
            and not _is_section_line(merged[-1])
            and not _is_list_line(merged[-1])
        ):
            merged[-1] = merged[-1].rstrip() + stripped
            i += 1
            continue

        # Soft-join mid-sentence English wraps: "...(4-8" + "Hz）"
        if (
            stripped
            and merged
            and merged[-1].strip()
            and not stripped.startswith("```")
            and not _is_list_line(stripped)
            and not _is_section_line(stripped)
            and not _is_section_line(merged[-1])
            and not _is_list_line(merged[-1])
            and not merged[-1].strip().startswith("```")
        ):
            prev = merged[-1].rstrip()
            if prev and prev[-1] not in "。！？!?…：:；;」』）)]":
                if (
                    stripped[0].islower()
                    or stripped[0].isdigit()
                    or stripped[0] in _NO_LINE_START
                    or re.match(r"^[A-Za-z]{1,12}\b", stripped)
                ):
                    gap = " "
                    if prev[-1] in "（([/" or stripped[0] in ")]}）」、，；：.":
                        gap = ""
                    merged[-1] = prev + gap + stripped
                    i += 1
                    continue

        # Preserve list markers through the merge pass (strip only in final clean)
        if _is_list_line(stripped):
            merged.append(stripped)
            i += 1
            continue

        # Orphan leading-punct paragraph right after a section → keep as body (strip punct)
        if stripped and stripped[0] in _NO_LINE_START and not _is_list_line(stripped):
            stripped = _strip_leading_punct(stripped)
            if not stripped:
                i += 1
                continue
            merged.append(_collapse_spaces(stripped))
            i += 1
            continue

        merged.append(_collapse_spaces(line) if stripped else "")
        i += 1

    cleaned: list[str] = []
    in_code = False
    for line in merged:
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            cleaned.append(line)
            continue
        if in_code:
            cleaned.append(line)
            continue
        if not s:
            cleaned.append("")
            continue
        if re.match(r"^【.+】", s) or s.startswith("## "):
            cleaned.append(s.strip())
        elif _is_list_line(s):
            if re.match(r"^[-•*]\s+", s):
                # Drop dash bullets → plain sentence
                body = _collapse_spaces(_strip_leading_punct(re.sub(r"^[-•*]\s+", "", s)))
                if body:
                    cleaned.append(body)
            else:
                # Keep human numbered lists: 1. xxx
                m_num = re.match(r"^(\d+)[.)、．]\s+(.*)$", s)
                if m_num:
                    body = _collapse_spaces(_strip_leading_punct(m_num.group(2)))
                    if body:
                        cleaned.append(f"{m_num.group(1)}. {body}")
        else:
            body = _collapse_spaces(_strip_leading_punct(s))
            if body:
                cleaned.append(body)
    return "\n".join(cleaned)


def _strip_md_noise(text: str) -> str:
    text = text.replace("\r", "")
    text = text.replace("\\*\\*\\*", "").replace("\\*\\*", "")
    text = re.sub(r"\*{3}(.+?)\*{3}", r"<B>\1</B>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<B>\1</B>", text)
    text = re.sub(r"__(.+?)__", r"<B>\1</B>", text)
    parts = re.split(r"(<B>.*?</B>)", text)
    out: list[str] = []
    for p in parts:
        if p.startswith("<B>") and p.endswith("</B>"):
            inner = _collapse_spaces(p[3:-4])
            out.append(f"<B>{inner}</B>")
        else:
            p = p.replace("***", "").replace("**", "").replace("*", "")
            p = p.replace("__", "")
            out.append(_collapse_spaces(p))
    return "".join(out)


def _plain(text: str) -> str:
    return _strip_leading_punct(re.sub(r"</?B>", "", _strip_md_noise(text)))


def _write_flow(pdf: FPDF, text: str, size: float, *, indent: float = 0) -> None:
    """Write one paragraph; never start a line with punctuation."""
    text = _strip_leading_punct(_strip_md_noise(text).strip())
    if not text:
        return
    pdf.set_text_color(*COMBINED)
    usable = PW - indent

    if pdf.get_y() > pdf.h - MB - LH * 3:
        pdf.add_page()

    pdf.set_font("C", "", size)
    pdf.set_x(pdf.l_margin + indent)
    body = _plain(text)
    for line in _wrap_cjk(pdf, body, usable):
        line = _strip_leading_punct(line)
        if not line:
            continue
        if pdf.get_y() > pdf.h - MB - LH:
            pdf.add_page()
        pdf.set_x(pdf.l_margin + indent)
        pdf.cell(usable, LH, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)


def _write_bullet(pdf: FPDF, text: str, size: float = 8.5) -> None:
    # Dash bullets → plain paragraph (prefer numbered lists in copy)
    body = _plain(re.sub(r"^[-•*]\s*", "", text.strip()))
    if not body:
        return
    _write_flow(pdf, body, size)


def _write_numbered(pdf: FPDF, num: str, text: str, size: float = 9) -> None:
    """Render human-style numbered item: 1. content"""
    body = _plain(text.strip())
    if not body:
        return
    if pdf.get_y() > pdf.h - MB - LH * 2:
        pdf.add_page()
    pdf.set_font("C", "", size)
    pdf.set_text_color(*COMBINED)
    prefix = f"{num}. "
    usable = PW - 2
    lines = _wrap_cjk(pdf, prefix + body, usable)
    for idx, line in enumerate(lines):
        if idx > 0:
            line = _strip_leading_punct(line)
        if not line:
            continue
        if pdf.get_y() > pdf.h - MB - LH:
            pdf.add_page()
        pdf.set_x(pdf.l_margin + 2)
        # Continuations indent under the text, not under the number
        pdf.cell(usable, LH, line if idx == 0 else f"   {line}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(0.8)


class ReportPDF(FPDF):
    def __init__(self) -> None:
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(True, MB)
        self.set_margins(ML, MT, MR)
        self.alias_nb_pages()
        self.add_font("C", "", FONT_PATH)
        self.add_font("CB", "", FONT_PATH_BOLD)
        self.ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.graph_img: str | None = None

    def footer(self) -> None:  # noqa: A003
        self.set_y(-MB + 4)
        self.set_draw_color(200, 200, 200)
        self.line(ML, self.get_y(), ML + PW, self.get_y())
        self.ln(2)
        self.set_font("C", "", 7)
        self.set_text_color(*GRAY)
        self.cell(PW / 2, 4, f"生成时间: {self.ts}", align="L")
        self.cell(PW / 2, 4, "参考信息，非医疗诊断  |  请咨询专业医生", align="R")

    def _section(self, title: str) -> None:
        # Plain section title — no fill/background (some viewers fail to paint text over fills)
        title = title.replace("<B>", "").replace("</B>", "")
        title = title.replace("【", "").replace("】", "").strip()
        title = _strip_leading_punct(_collapse_spaces(title))
        if not title:
            return
        self.ln(4)
        if self.get_y() > 250:
            self.add_page()
        self.set_x(self.l_margin)
        self.set_font("CB", "", 12)
        self.set_text_color(*BLUE)
        self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(220, 230, 245)
        self.set_line_width(0.3)
        y = self.get_y()
        self.line(ML, y, ML + PW, y)
        self.ln(3)

    def _image_block(self, img_b64: str) -> bool:
        """Embed PNG graph. Advances Y past the image to avoid overlap."""
        tmp: str | None = None
        try:
            raw = (img_b64 or "").strip()
            if not raw:
                raise ValueError("empty image")
            if "," in raw and raw.lower().startswith("data:"):
                raw = raw.split(",", 1)[1]
            data = base64.b64decode(raw)
            if len(data) < 100:
                raise ValueError("image too small")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(data)
                tmp = f.name

            # Aspect ratio from PNG header via fpdf image info if possible
            img_w = PW - 6
            img_h = min(img_w * 0.55, GRAPH_MAX_H)
            try:
                from PIL import Image

                with Image.open(tmp) as im:
                    iw, ih = im.size
                    if iw > 0 and ih > 0:
                        img_h = min(img_w * (ih / iw), GRAPH_MAX_H)
            except Exception:
                pass

            y = self.get_y()
            if y + img_h + 12 > self.h - MB:
                self.add_page()
                y = self.get_y()

            # No filled frame behind image — draw stroke only (fills can hide content in some viewers)
            self.set_draw_color(220, 220, 220)
            self.rect(ML + 1, y, img_w + 4, img_h + 4, style="D")
            self.image(tmp, x=ML + 3, y=y + 2, w=img_w, h=img_h)
            # Critical: manually move cursor below image (image() does not advance Y)
            self.set_y(y + img_h + 8)
            return True
        except Exception:
            self.ln(2)
            self.set_fill_color(255, 245, 230)
            self.set_draw_color(255, 180, 50)
            y = self.get_y()
            self.rect(ML + 2, y, PW - 4, 10, "DF")
            self.set_xy(ML + 6, y + 2.5)
            self.set_font("C", "", 8)
            self.set_text_color(160, 100, 20)
            self.cell(0, 5, "核心回路图未能嵌入（截图为空或格式异常），回路文字分析仍可查看。")
            self.set_y(y + 12)
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


def generate_report_pdf(
    report_md: str,
    circuits: list | None = None,
    graph_b64: str | None = None,
) -> io.BytesIO:
    """Generate professional A4 PDF report with optional circuit graph image."""
    del circuits  # reserved for future structured tables
    pdf = ReportPDF()
    pdf.graph_img = graph_b64 if isinstance(graph_b64, str) else None
    pdf.add_page()

    # Title
    pdf.set_font("CB", "", 18)
    pdf.set_text_color(*BLUE)
    pdf.cell(0, 9, "脑部健康分析报告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font("C", "", 8)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, "基于 NeuroGraphIQ 知识图谱回路分析", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.35)
    y = pdf.get_y() + 1
    pdf.line(ML, y, ML + PW, y)
    pdf.ln(6)

    md = _normalize_markdown(report_md or "")

    lines = md.split("\n")
    i = 0
    section_idx = 0
    graph_placed = False
    in_code = False
    code_buf: list[str] = []
    list_buf: list[str] = []

    def flush_list() -> None:
        nonlocal list_buf
        for item in list_buf:
            _write_bullet(pdf, item)
        list_buf = []

    def maybe_place_graph(title: str) -> None:
        nonlocal graph_placed
        if graph_placed or not pdf.graph_img:
            return
        # Prefer section 2 / titles that mention 回路
        title_l = title.lower()
        want = section_idx == 2 or ("回路" in title) or ("circuit" in title_l)
        if not want:
            return
        ok = pdf._image_block(pdf.graph_img)
        graph_placed = True
        if ok:
            _write_flow(
                pdf,
                "上图展示了系统匹配的核心神经回路连接关系：节点表示脑区，连线表示神经投射通路。",
                8,
            )

    while i < len(lines):
        ln = lines[i].rstrip()
        stripped = ln.strip()

        if stripped.startswith("```"):
            if in_code:
                if code_buf:
                    pdf.set_font("C", "", 7)
                    pdf.set_fill_color(248, 250, 252)
                    pdf.set_text_color(*COMBINED)
                    block = "\n".join(cl[:140] for cl in code_buf)
                    # Estimate height
                    h = max(10, len(code_buf) * 3.8 + 6)
                    if pdf.get_y() + h > pdf.h - MB:
                        pdf.add_page()
                    y0 = pdf.get_y()
                    pdf.rect(ML + 2, y0, PW - 4, h, "DF")
                    pdf.set_xy(ML + 4, y0 + 2)
                    pdf.multi_cell(w=PW - 8, h=3.6, text=block, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_y(max(pdf.get_y(), y0 + h + 2))
                    code_buf = []
                in_code = False
            else:
                flush_list()
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(stripped)
            i += 1
            continue

        if not stripped or re.match(r"^[-*_]{3,}$", stripped):
            flush_list()
            i += 1
            continue

        m = re.match(r"^【(.+?)】(.*)$", stripped)
        if m:
            flush_list()
            title = m.group(1).strip()
            rest = m.group(2).strip()
            pdf._section(title)
            section_idx += 1
            maybe_place_graph(title)
            if rest:
                _write_flow(pdf, rest, 9)
            i += 1
            continue

        # Markdown ## headers
        if stripped.startswith("## "):
            flush_list()
            title = stripped[3:].strip()
            pdf._section(title)
            section_idx += 1
            maybe_place_graph(title)
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("• ") or stripped.startswith("* "):
            flush_list()
            _write_flow(pdf, re.sub(r"^[-•*]\s+", "", stripped), 9)
            i += 1
            continue

        flush_list()

        m_num = re.match(r"^(\d+)[.)、．]\s+(.+)$", stripped)
        if m_num:
            _write_numbered(pdf, m_num.group(1), m_num.group(2))
            i += 1
            continue

        _write_flow(pdf, stripped, 9)
        i += 1

    flush_list()

    # Fallback: graph never matched a section header
    if pdf.graph_img and not graph_placed:
        pdf._section("核心回路图谱")
        pdf._image_block(pdf.graph_img)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
