"""Convert clinical markdown report to 2-page A4 PDF using fpdf2."""
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import os

class ClinicalPDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', 'I', 7)
        self.cell(0, 8, f'{self.page_no()}/{{nb}}', align='C')

def generate_pdf(md_path: str, pdf_path: str):
    pdf = ClinicalPDF('P', 'mm', 'A4')
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, 12)
    pdf.add_font('CJK', '', r'C:\Windows\Fonts\msyh.ttc')  # Microsoft YaHei
    pdf.add_page()

    with open(md_path, encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')

    for line in lines:
        text = line.strip()
        if not text:
            pdf.ln(1.5)
            continue

        if text.startswith('# '):  # Title
            pdf.set_font('CJK', '', 18)
            pdf.set_text_color(0, 40, 80)
            pdf.cell(0, 8, text[2:], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_draw_color(0, 40, 80)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)

        elif text.startswith('## '):  # H2 heading
            pdf.set_font('CJK', '', 12)
            pdf.set_text_color(0, 40, 80)
            pdf.ln(1)
            pdf.cell(0, 6, text[3:], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        elif text.startswith('### '):  # H3 heading
            pdf.set_font('CJK', '', 10)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 5, text[4:], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        elif text.startswith('---'):  # Horizontal rule
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(1)

        elif text.startswith('**') and '：' in text:  # Bold metadata
            pdf.set_font('CJK', '', 9)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 4.5, text.replace('**', ''), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        elif text.startswith('- ') or text.startswith('  - '):  # List items
            pdf.set_font('CJK', '', 8)
            pdf.set_text_color(50, 50, 50)
            indent = 12
            pdf.set_x(indent)
            # Split long lines
            item_text = text.lstrip('- ')
            pdf.multi_cell(w=185 - indent, h=3.5, text=f'• {item_text}')

        elif text.startswith('1. ') or text.startswith('2. ') or text.startswith('3. ') or text.startswith('4. '):
            pdf.set_font('CJK', '', 7.5)
            pdf.set_text_color(50, 50, 50)
            pdf.multi_cell(w=185, h=3.5, text=text)

        else:  # Regular paragraph
            pdf.set_font('CJK', '', 7.5)
            pdf.set_text_color(50, 50, 50)
            pdf.multi_cell(w=185, h=3.5, text=text)

    pdf.output(pdf_path)
    print(f'PDF: {pdf_path}')
    print(f'Pages: {pdf.page_no()}')
    print(f'Size: {os.path.getsize(pdf_path)/1024:.0f} KB')


if __name__ == '__main__':
    import sys
    md = sys.argv[1] if len(sys.argv) > 1 else 'docs/brain_3d/clinical_brain_analysis_report.md'
    pdf = sys.argv[2] if len(sys.argv) > 2 else 'docs/brain_3d/clinical_brain_analysis_report.pdf'
    generate_pdf(md, pdf)
