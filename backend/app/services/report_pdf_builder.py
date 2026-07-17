"""Report PDF Builder — Professional A4 clinical report with proper typography.

Handles:
- Markdown parsing (bold, lists, code blocks)
- A4 layout with headers/footers
- Chinese font embedding
- Page break control (widows/orphans)
- Template/data separation
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos


# ── Configuration ────────────────────────────────────────────────────────

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"      # Microsoft YaHei
FONT_PATH_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"  # Microsoft YaHei Bold

# Margins (mm)
MARGIN_TOP = 20
MARGIN_BOTTOM = 20
MARGIN_LEFT = 18
MARGIN_RIGHT = 18

# Colors (RGB)
COLOR_PRIMARY = (22, 119, 255)       # #1677ff 主色
COLOR_PRIMARY_DARK = (9, 88, 217)    # #0958d9
COLOR_HEADING_BG = (240, 245, 255)   # 章节标题背景
COLOR_CARD_BG = (248, 250, 252)      # 回路卡片背景
COLOR_BORDER = (220, 224, 230)       # 边框
COLOR_TEXT = (51, 51, 51)             # 正文
COLOR_TEXT_MUTED = (134, 144, 156)    # 辅助文字
COLOR_BLACK = (0, 0, 0)

# Font sizes (pt)
FONT_TITLE = 22
FONT_H1 = 14
FONT_H2 = 11.5
FONT_BODY = 9.5
FONT_SMALL = 8

# Line height multiplier
LINE_HEIGHT = 1.5
BODY_LEADING = FONT_BODY * 0.3528 * LINE_HEIGHT  # mm

CONTENT_WIDTH = 210 - MARGIN_LEFT - MARGIN_RIGHT  # 174mm


# ── Markdown Parser ──────────────────────────────────────────────────────

def parse_markdown_to_blocks(text: str) -> list[dict]:
    """Parse markdown text into structured blocks for PDF rendering."""
    blocks: list[dict] = []
    lines = text.split("\n")
    i = 0
    in_code = False
    code_lines: list[str] = []

    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith("```"):
            if in_code:
                blocks.append({"type": "code", "lines": code_lines})
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # Empty line
        if not line.strip():
            blocks.append({"type": "spacer", "height": 2})
            i += 1
            continue

        # Section header 【...】
        m = re.match(r"^【(.+)】$", line.strip())
        if m:
            blocks.append({"type": "section", "text": m.group(1)})
            i += 1
            continue

        # Sub-header (bold line on its own, like a circuit name)
        m_bold = re.match(r"^\*\*(.+)\*\*$", line.strip())
        if m_bold:
            blocks.append({"type": "sub_header", "text": m_bold.group(1)})
            i += 1
            continue

        # Bullet list items
        if re.match(r"^-\s", line.strip()):
            items = []
            while i < len(lines) and re.match(r"^-\s", lines[i].strip()):
                items.append(re.sub(r"^-\s+", "", lines[i].strip()))
                i += 1
            blocks.append({"type": "list", "items": items})
            continue

        # Regular paragraph
        para_lines = []
        while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("```") and not re.match(r"^【.+】$", lines[i].strip()) and not re.match(r"^-\s", lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            blocks.append({"type": "paragraph", "text": " ".join(para_lines)})

    return blocks


def render_inline_bold(pdf: FPDF, text: str) -> None:
    """Write text with **bold** spans properly rendered."""
    parts = re.split(r"(\*\*(?:[^*]+|\*(?!\*))*\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            pdf.set_font("CJKBold", "", FONT_BODY)
            pdf.write(h=BODY_LEADING, text=part[2:-2])
        else:
            pdf.set_font("CJK", "", FONT_BODY)
            pdf.write(h=BODY_LEADING, text=part)


# ── PDF Builder ──────────────────────────────────────────────────────────

class ReportPDF(FPDF):
    """Professional A4 clinical brain analysis report."""

    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(True, MARGIN_BOTTOM)
        self.set_margin(MARGIN_LEFT)
        self.alias_nb_pages()

        # Register fonts
        self.add_font("CJK", "", FONT_PATH)
        self.add_font("CJKBold", "", FONT_PATH_BOLD)

        # Metadata
        self.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.page_count_est = 0

    # ── Header/Footer ────────────────────────────────────────────────────

    def header(self):
        if self.page_no() == 1:
            return  # Title page handles its own header
        self.set_font("CJK", "", FONT_SMALL)
        self.set_text_color(*COLOR_TEXT_MUTED)
        self.cell(0, 6, "NeuroGraphIQ", align="L")
        self.cell(0, 6, "脑部健康分析报告", align="R")
        self.ln(4)
        self.set_draw_color(*COLOR_BORDER)
        self.line(MARGIN_LEFT, self.get_y(), 210 - MARGIN_RIGHT, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-MARGIN_BOTTOM + 2)
        self.set_font("CJK", "", FONT_SMALL)
        self.set_text_color(*COLOR_TEXT_MUTED)
        page_text = f"第 {self.page_no()} 页 / 共 {{nb}} 页"
        self.cell(0, 5, page_text, align="C")
        self.ln(3.5)
        self.cell(0, 4, "参考信息，非医疗诊断", align="C")
        if self.generated_at and self.page_no() == 1:
            self.ln(1)

    # ── Title Page ───────────────────────────────────────────────────────

    def render_title_page(self):
        """Render the title block at the top of page 1."""
        self.set_font("CJKBold", "", FONT_TITLE)
        self.set_text_color(*COLOR_PRIMARY)
        self.cell(0, 10, "脑部健康分析报告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.ln(2)

        self.set_font("CJK", "", 9)
        self.set_text_color(*COLOR_TEXT_MUTED)
        self.cell(0, 5, "基于 NeuroGraphIQ 知识图谱回路分析", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.ln(1)
        self.cell(0, 4, f"生成时间: {self.generated_at}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.ln(2)

        # Disclaimer bar
        self.set_fill_color(240, 245, 255)
        self.set_draw_color(*COLOR_PRIMARY)
        self.rect(MARGIN_LEFT + 20, self.get_y(), CONTENT_WIDTH - 40, 6, style="DF")
        self.set_font("CJK", "", 7.5)
        self.set_text_color(*COLOR_TEXT_MUTED)
        self.cell(0, 6, "参考信息，非医疗诊断  |  请咨询神经内科医生获得专业诊断意见", align="C")
        self.ln(4)

        # Separator line
        self.set_draw_color(*COLOR_PRIMARY)
        self.set_line_width(0.4)
        self.line(MARGIN_LEFT, self.get_y(), 210 - MARGIN_RIGHT, self.get_y())
        self.set_line_width(0.2)
        self.ln(5)

    # ── Section Header ───────────────────────────────────────────────────

    def render_section(self, title: str):
        """Render a chapter heading with left blue bar."""
        self.ln(3)
        y = self.get_y()

        # Check if there's room for heading + 2 lines of body
        if y > 270:
            self.add_page()

        # Blue left bar
        self.set_fill_color(*COLOR_PRIMARY)
        self.rect(MARGIN_LEFT, y, 2.5, 7, style="F")
        # Light blue background
        self.set_fill_color(*COLOR_HEADING_BG)
        self.rect(MARGIN_LEFT, y, CONTENT_WIDTH, 7, style="F")

        self.set_xy(MARGIN_LEFT + 6, y + 0.5)
        self.set_font("CJKBold", "", FONT_H1)
        self.set_text_color(*COLOR_PRIMARY_DARK)
        self.cell(0, 6, title)
        self.ln(10)

    # ── Card ──────────────────────────────────────────────────────────────

    def render_card(self, lines: list[tuple[str, str]]):
        """Render a card with labeled lines. Each tuple is (label, value)."""
        self.set_fill_color(*COLOR_CARD_BG)
        self.set_draw_color(*COLOR_BORDER)

        # Calculate needed height
        card_h = len(lines) * 5.5 + 6
        y_start = self.get_y()

        # Check if card fits on current page
        if y_start + card_h > 270:
            self.add_page()
            y_start = self.get_y()

        self.rect(MARGIN_LEFT + 2, y_start, CONTENT_WIDTH - 4, card_h, style="DF")
        self.set_xy(MARGIN_LEFT + 6, y_start + 3)

        for label, value in lines:
            self.set_font("CJKBold", "", FONT_BODY)
            self.set_text_color(*COLOR_BLACK)
            self.cell(22, 5.5, label + "：")
            self.set_font("CJK", "", FONT_BODY)
            self.set_text_color(*COLOR_TEXT)
            self.cell(0, 5.5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(MARGIN_LEFT + 6)
        self.ln(3)

    # ── ASCII diagram ────────────────────────────────────────────────────

    def render_diagram(self, d_lines: list[str]):
        """Render ASCII diagram in a bordered box."""
        if not d_lines:
            return
        dia_h = len(d_lines) * 3.8 + 6
        y = self.get_y()
        if y + dia_h > 270:
            self.add_page()

        self.set_fill_color(248, 250, 252)
        self.set_draw_color(*COLOR_BORDER)
        self.rect(MARGIN_LEFT + 6, y, CONTENT_WIDTH - 12, dia_h, style="DF")

        self.set_xy(MARGIN_LEFT + 10, y + 3)
        self.set_font("CJK", "", 7.5)  # Use CJK for Chinese diagram labels
        self.set_text_color(85, 85, 85)
        for dline in d_lines:
            self.cell(0, 3.8, dline, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(MARGIN_LEFT + 10)
        self.ln(3)

    # ── Suggestion Block ─────────────────────────────────────────────────

    def render_suggestion(self, num: str, title: str, items: list[str]):
        """Render a numbered suggestion block."""
        self.set_fill_color(*COLOR_HEADING_BG)
        self.set_draw_color(*COLOR_PRIMARY)
        y = self.get_y()

        self.rect(MARGIN_LEFT + 2, y, CONTENT_WIDTH - 4, len(items) * 5 + 10, style="DF")
        self.set_xy(MARGIN_LEFT + 8, y + 3)

        self.set_font("CJKBold", "", FONT_BODY)
        self.set_text_color(*COLOR_PRIMARY_DARK)
        self.cell(0, 5, f"{num}. {title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        for item in items:
            self.set_x(MARGIN_LEFT + 12)
            self.set_font("CJK", "", FONT_BODY)
            self.set_text_color(*COLOR_TEXT)
            self.cell(3, 5, "•")
            self.multi_cell(w=CONTENT_WIDTH - 24, h=5, text=item)
        self.ln(3)


# ── Public API ────────────────────────────────────────────────────────────

def generate_report_pdf(report_md: str, circuits: list[dict] | None = None) -> io.BytesIO:
    """Generate a professional A4 PDF from DeepSeek markdown report.

    Args:
        report_md: Raw markdown text from DeepSeek
        circuits: Optional list of circuit dicts from the system

    Returns:
        BytesIO buffer containing the PDF
    """
    pdf = ReportPDF()
    pdf.add_page()

    # Title page
    pdf.render_title_page()

    # Parse markdown into blocks
    blocks = parse_markdown_to_blocks(report_md)

    # Render blocks
    for block in blocks:
        t = block["type"]

        if t == "spacer":
            pdf.ln(block.get("height", 2))

        elif t == "section":
            pdf.render_section(block["text"])

        elif t == "sub_header":
            pdf.set_font("CJKBold", "", FONT_BODY)
            pdf.set_text_color(*COLOR_BLACK)
            pdf.cell(0, 6, block["text"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)

        elif t == "paragraph":
            pdf.set_font("CJK", "", FONT_BODY)
            pdf.set_text_color(*COLOR_TEXT)
            render_inline_bold(pdf, block["text"])
            pdf.ln(4)

        elif t == "list":
            for item in block["items"]:
                pdf.set_font("CJK", "", FONT_BODY)
                pdf.set_text_color(*COLOR_TEXT)
                item_text = item
                if item_text.startswith("• ") or item_text.startswith("- "):
                    item_text = item_text[2:]
                pdf.set_x(MARGIN_LEFT + 4)
                pdf.cell(3, BODY_LEADING, "•")
                render_inline_bold(pdf, item_text)
                pdf.ln(1.5)
            pdf.ln(1)

        elif t == "code":
            pdf.ln(1)
            pdf.render_diagram(block["lines"])
            pdf.ln(1)

        # Check for page bottom orphan — if near bottom, push to next page
        if pdf.get_y() > 268:
            pdf.add_page()

    # ── Footer disclaimer ─────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_draw_color(*COLOR_PRIMARY)
    pdf.line(MARGIN_LEFT, pdf.get_y(), 210 - MARGIN_RIGHT, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("CJK", "", 7.5)
    pdf.set_text_color(*COLOR_TEXT_MUTED)
    pdf.multi_cell(w=CONTENT_WIDTH, h=4, text="本报告由NeuroGraphIQ知识图谱系统自动生成，结合患者症状描述与脑回路匹配数据。报告内容仅供健康参考，不构成医疗诊断。如有健康问题，请及时咨询专业医生。")

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
