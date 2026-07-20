"""Report PDF Builder — Clean, professional A4 layout. No overlaps."""
from __future__ import annotations

import io, re
from datetime import datetime, timezone
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ── Config ─────────────────────────────────────────────────────────────
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
FONT_PATH_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
ML, MR, MT, MB = 20, 20, 20, 20             # margins (mm)
PW = 210 - ML - MR                            # printable width (170mm)
LH = 5.5                                      # body line height (mm)
C1 = (22, 119, 255)                           # primary blue
CG = (100, 100, 100)                          # gray text


def _esc(text: str) -> str:
    """Replace unsupported Unicode chars with ASCII fallbacks."""
    return text.replace('—', '—').replace('–', '–').replace('‘', "'").replace('’', "'").replace('“', '"').replace('”', '"').replace('…', '...').replace('（', '(').replace('）', ')').replace('，', ',').replace('、', ',').replace('：', ':').replace('；', ';')


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(True, MB)
        self.set_left_margin(ML)
        self.alias_nb_pages()
        self.add_font("C", "", FONT_PATH)
        self.add_font("CB", "", FONT_PATH_BOLD)
        self.ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def header(self):
        if self.page_no() == 1: return
        self.set_font("C", "", 7); self.set_text_color(*CG)
        self.cell(0, 4, "NeuroGraphIQ  |  脑部健康分析报告", align="R")
        self.ln(5)

    def footer(self):
        self.set_y(-MB + 4)
        self.set_font("C", "", 7); self.set_text_color(*CG)
        self.cell(0, 4, f"第 {self.page_no()} 页 / 共 {{nb}} 页  |  参考信息，非医疗诊断", align="C")

    # ── Block helpers ───────────────────────────────────────────────────

    def _h1(self, text: str):
        """Section header: blue bar + bold text."""
        self.ln(4)
        self.set_fill_color(240, 245, 255)
        self.set_draw_color(*C1)
        y = self.get_y()
        self.rect(ML, y, 2.5, 6, "F")
        self.set_xy(ML + 6, y)
        self.set_font("CB", "", 13); self.set_text_color(*C1)
        self.cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def _h2(self, text: str):
        """Sub-header: bold, slightly larger."""
        self.ln(2)
        self.set_font("CB", "", 10.5); self.set_text_color(40, 40, 40)
        self.cell(0, 5.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def _p(self, text: str):
        """Paragraph with inline bold support."""
        self.set_font("C", "", 9); self.set_text_color(60, 60, 60)
        for part in re.split(r"(\*\*(?:[^*]+|\*(?!\*))*\*\*)", _esc(text)):
            if part.startswith("**") and part.endswith("**"):
                self.set_font("CB", "", 9)
                self.write(LH, part[2:-2])
                self.set_font("C", "", 9)
            else:
                self.write(LH, part)
        self.ln(3)

    def _li(self, items: list[str]):
        """Bullet list."""
        self.set_font("C", "", 8.5); self.set_text_color(60, 60, 60)
        indent = ML + 4
        for item in items:
            self.set_x(indent)
            self.cell(3, LH, "•")
            self.multi_cell(PW - 7, LH, _esc(re.sub(r"^[-•]\s*", "", item.strip())))
            self.ln(0.5)
        self.ln(1)

    def _code(self, lines: list[str]):
        """Code block / diagram."""
        self.ln(1)
        self.set_fill_color(248, 250, 252)
        self.set_draw_color(200, 200, 200)
        h = len(lines) * 3.5 + 4
        y = self.get_y()
        if y + h > 270: self.add_page()
        self.rect(ML + 4, y, PW - 8, h, "DF")
        self.set_xy(ML + 8, y + 2)
        self.set_font("C", "", 7); self.set_text_color(120, 120, 120)
        for ln in lines:
            self.cell(0, 3.5, ln, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(ML + 8)
        self.ln(3)

    def _card(self, label_pairs: list[tuple[str, str]]):
        """Simple bordered card for circuit info."""
        self.ln(1)
        self.set_fill_color(248, 250, 252)
        self.set_draw_color(210, 214, 220)
        lines = len(label_pairs)
        h = lines * 5 + 6
        y = self.get_y()
        if y + h > 270: self.add_page()
        self.rect(ML + 2, y, PW - 4, h, "DF")
        self.set_xy(ML + 6, y + 3)
        for label, value in label_pairs:
            self.set_font("CB", "", 8.5); self.set_text_color(40, 40, 40)
            self.cell(24, 5, label + "：")
            self.set_font("C", "", 8.5); self.set_text_color(60, 60, 60)
            self.cell(PW - 34, 5, _esc(value)[:120], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(ML + 6)
        self.ln(3)

    def _suggestion(self, num: str, title: str, items: list[str]):
        """Numbered suggestion block."""
        self.ln(1)
        self.set_fill_color(240, 245, 255)
        self.set_draw_color(180, 200, 230)
        item_h = len(items) * 5 + 10
        y = self.get_y()
        if y + item_h > 270: self.add_page()
        self.rect(ML + 2, y, PW - 4, item_h, "DF")
        self.set_xy(ML + 8, y + 3)
        self.set_font("CB", "", 9); self.set_text_color(*C1)
        self.cell(0, 5, f"{num}. {title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("C", "", 8.5); self.set_text_color(60, 60, 60)
        for item in items:
            self.set_x(ML + 12)
            self.multi_cell(PW - 16, 5, _esc(item))
        self.ln(2)


# ── Public API ──────────────────────────────────────────────────────────

def generate_report_pdf(report_md: str, circuits: list | None = None) -> io.BytesIO:
    """Generate clean A4 PDF from markdown report text."""
    pdf = ReportPDF()
    pdf.add_page()

    # ── Title ──────────────────────────────────────────────────────────
    pdf.set_font("CB", "", 20); pdf.set_text_color(*C1)
    pdf.cell(0, 10, "脑部健康分析报告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font("C", "", 8); pdf.set_text_color(*CG)
    pdf.cell(0, 5, "基于 NeuroGraphIQ 知识图谱回路分析", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(0, 4, f"生成时间: {pdf.ts}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(2)
    pdf.set_draw_color(*C1); pdf.set_line_width(0.3)
    pdf.line(ML, pdf.get_y(), ML + PW, pdf.get_y()); pdf.ln(3)
    pdf.set_font("C", "", 7); pdf.set_text_color(*CG)
    pdf.multi_cell(PW, 4, "免责声明：本报告由 AI 辅助生成，结合症状描述与脑回路数据。仅供参考，不构成医疗诊断。如有健康问题，请咨询神经内科医生。")
    pdf.ln(4)

    # ── Body ───────────────────────────────────────────────────────────
    # Clean markdown
    md = re.sub(r'^[-*_]{3,}\s*$', '', report_md, flags=re.MULTILINE)
    md = md.replace('\\*\\*\\*', '')
    md = re.sub(r'\*\*\*(.+?)\*\*\*', r'**\1**', md)
    md = re.sub(r'^\s*---+\s*$', '', md, flags=re.MULTILINE)

    lines = md.split('\n')
    i = 0
    in_code = False
    code_buf: list[str] = []
    list_buf: list[str] = []

    while i < len(lines):
        ln = lines[i].strip()

        # Code block
        if ln.startswith('```'):
            if in_code:
                if code_buf: pdf._code(code_buf); code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1; continue
        if in_code:
            code_buf.append(ln); i += 1; continue

        # Skip empty / horizontal rule
        if not ln or re.match(r'^[-*_]{3,}$', ln):
            if list_buf: pdf._li(list_buf); list_buf = []
            i += 1; continue

        # Section header
        m = re.match(r'^【(.+)】$', ln)
        if m:
            if list_buf: pdf._li(list_buf); list_buf = []
            pdf._h1(m.group(1))
            i += 1; continue

        # Sub-header (bold standalone line)
        m = re.match(r'^\*\*(.+)\*\*$', ln)
        if m:
            if list_buf: pdf._li(list_buf); list_buf = []
            pdf._h2(m.group(1))
            i += 1; continue

        # Bullet
        if ln.startswith('- ') or ln.startswith('• '):
            list_buf.append(ln)
            i += 1; continue
        if list_buf:
            pdf._li(list_buf); list_buf = []

        # Numbered item
        m = re.match(r'^(\d+)\.\s+(.+)$', ln)
        if m:
            pdf._p(f"**{m.group(1)}.** {m.group(2)}")
            i += 1; continue

        # Regular paragraph
        pdf._p(ln)
        i += 1

    if list_buf: pdf._li(list_buf)

    # ── Footer disclaimer ──────────────────────────────────────────────
    pdf.ln(3)
    pdf.set_draw_color(200, 200, 200); pdf.line(ML, pdf.get_y(), ML + PW, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("C", "", 7); pdf.set_text_color(*CG)
    pdf.multi_cell(PW, 4, "本报告由 NeuroGraphIQ 知识图谱系统生成，结合患者症状描述与脑回路匹配数据。报告内容仅供健康参考，不构成医疗诊断。如有健康问题，请及时咨询专业医生。")

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
