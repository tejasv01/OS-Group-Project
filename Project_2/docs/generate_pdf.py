#!/usr/bin/env python3
import sys, os, re

def escape_pdf_text(text):
    # Normalize common Unicode characters to clean ASCII representations
    replacements = {
        '\u2014': ' -- ',
        '\u2013': '-',
        '\u2018': "'",
        '\u2019': "'",
        '\u201c': '"',
        '\u201d': '"',
        '\u2022': '*',
        '\u2192': '->',
        '\u2190': '<-',
        '\u2264': '<=',
        '\u2265': '>=',
        '\u2208': ' in ',
        '\u2248': '~',
        '\u00d7': 'x',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = text.encode('ascii', 'replace').decode('ascii')
    text = text.replace('\\', '\\\\')
    text = text.replace('(', '\\(')
    text = text.replace(')', '\\)')
    return text

class SimplePDFBuilder:
    def __init__(self, filename="output.pdf"):
        self.filename = filename
        self.pages = []
        self.current_page_ops = []
        self.page_width = 612
        self.page_height = 792
        self.margin_left = 50
        self.margin_right = 562
        self.margin_top = 740
        self.margin_bottom = 50
        self.cursor_y = self.margin_top

    def new_page(self):
        if self.current_page_ops:
            self.pages.append(self.current_page_ops)
            self.current_page_ops = []
        self.cursor_y = self.margin_top

    def ensure_space(self, needed_pt):
        if self.cursor_y - needed_pt < self.margin_bottom:
            self.new_page()

    def add_op(self, op):
        self.current_page_ops.append(op)

    def draw_text(self, x, y, font, size, text, color=(0,0,0)):
        r, g, b = color
        safe = escape_pdf_text(text)
        op = f"{r:.2f} {g:.2f} {b:.2f} rg BT /{font} {size} Tf {x:.2f} {y:.2f} Td ({safe}) Tj ET"
        self.add_op(op)

    def draw_rect(self, x, y, w, h, fill_color=None, stroke_color=None, line_width=1):
        ops = []
        if line_width:
            ops.append(f"{line_width} w")
        if stroke_color:
            r, g, b = stroke_color
            ops.append(f"{r:.2f} {g:.2f} {b:.2f} RG")
        if fill_color:
            r, g, b = fill_color
            ops.append(f"{r:.2f} {g:.2f} {b:.2f} rg")
        ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re")
        if fill_color and stroke_color:
            ops.append("B")
        elif fill_color:
            ops.append("f")
        elif stroke_color:
            ops.append("S")
        self.add_op(" ".join(ops))

    def draw_line(self, x1, y1, x2, y2, color=(0.7,0.7,0.7), width=1):
        r, g, b = color
        op = f"{width} w {r:.2f} {g:.2f} {b:.2f} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        self.add_op(op)

    def add_title(self, text, subtitle=None):
        self.ensure_space(110)
        # Decorative banner box
        self.draw_rect(self.margin_left, self.cursor_y - 85, self.margin_right - self.margin_left, 85,
                       fill_color=(0.08, 0.22, 0.42), stroke_color=(0.05, 0.15, 0.30), line_width=2)
        self.draw_text(self.margin_left + 15, self.cursor_y - 32, "F2", 18, text, color=(1, 1, 1))
        if subtitle:
            self.draw_text(self.margin_left + 15, self.cursor_y - 56, "F1", 11, subtitle, color=(0.85, 0.92, 1.0))
        self.draw_text(self.margin_left + 15, self.cursor_y - 74, "F1", 9,
                       "Course: Operating Systems | Target: xv6-riscv (RISC-V 64-bit) | Authors: Rohit & Sarthak",
                       color=(0.75, 0.85, 0.95))
        self.cursor_y -= 105

    def add_heading1(self, text):
        self.ensure_space(55)
        self.cursor_y -= 10
        # Accent bar
        self.draw_rect(self.margin_left, self.cursor_y - 22, 4, 22, fill_color=(0.12, 0.35, 0.65))
        self.draw_text(self.margin_left + 12, self.cursor_y - 18, "F2", 14, text, color=(0.10, 0.25, 0.45))
        self.draw_line(self.margin_left, self.cursor_y - 25, self.margin_right, self.cursor_y - 25,
                       color=(0.75, 0.82, 0.92), width=1)
        self.cursor_y -= 38

    def add_heading2(self, text):
        self.ensure_space(38)
        self.cursor_y -= 6
        self.draw_text(self.margin_left, self.cursor_y - 14, "F2", 11, text, color=(0.15, 0.30, 0.50))
        self.cursor_y -= 24

    def add_heading3(self, text):
        self.ensure_space(28)
        self.draw_text(self.margin_left, self.cursor_y - 12, "F2", 9.5, text, color=(0.20, 0.20, 0.20))
        self.cursor_y -= 18

    def add_paragraph(self, text):
        # Word wrap text to 512 pt width (approx 85-90 chars at 9pt Helvetica)
        words = text.split()
        if not words:
            self.cursor_y -= 6
            return

        lines = []
        cur_line = []
        cur_len = 0
        max_chars = 95 # at 9pt font

        for w in words:
            if cur_len + len(w) + 1 > max_chars:
                lines.append(" ".join(cur_line))
                cur_line = [w]
                cur_len = len(w)
            else:
                cur_line.append(w)
                cur_len += len(w) + 1
        if cur_line:
            lines.append(" ".join(cur_line))

        line_height = 12.5
        for line in lines:
            self.ensure_space(line_height + 2)
            self.draw_text(self.margin_left, self.cursor_y - 9, "F1", 9, line, color=(0.15, 0.15, 0.15))
            self.cursor_y -= line_height
        self.cursor_y -= 4

    def add_code_block(self, lines):
        if not lines:
            return
        line_height = 10.5
        total_height = len(lines) * line_height + 12
        
        # Check if entire block fits, else chunk it across pages
        i = 0
        while i < len(lines):
            avail = self.cursor_y - self.margin_bottom - 15
            lines_fit = max(1, int(avail // line_height))
            chunk = lines[i : i + lines_fit]
            chunk_h = len(chunk) * line_height + 10

            self.ensure_space(chunk_h + 5)
            # Background box
            self.draw_rect(self.margin_left, self.cursor_y - chunk_h,
                           self.margin_right - self.margin_left, chunk_h,
                           fill_color=(0.95, 0.96, 0.98), stroke_color=(0.82, 0.85, 0.90), line_width=1)

            text_y = self.cursor_y - 10
            for code_line in chunk:
                # Truncate line if too long for box
                safe_line = code_line[:110]
                self.draw_text(self.margin_left + 8, text_y, "F3", 7.5, safe_line, color=(0.10, 0.12, 0.20))
                text_y -= line_height
            self.cursor_y -= chunk_h + 8
            i += len(chunk)

    def add_table(self, rows):
        if not rows:
            return
        ncols = max((len(r) for r in rows), default=0)
        if ncols == 0:
            return
        col_width = (self.margin_right - self.margin_left) / ncols
        row_height = 14

        for r_idx, row in enumerate(rows):
            self.ensure_space(row_height + 4)
            is_header = (r_idx == 0)
            bg_color = (0.90, 0.93, 0.98) if is_header else ((0.98, 0.98, 0.98) if r_idx % 2 == 0 else (1, 1, 1))
            self.draw_rect(self.margin_left, self.cursor_y - row_height,
                           self.margin_right - self.margin_left, row_height,
                           fill_color=bg_color, stroke_color=(0.80, 0.83, 0.88), line_width=0.75)

            font = "F2" if is_header else "F1"
            txt_color = (0.1, 0.2, 0.35) if is_header else (0.15, 0.15, 0.15)
            for c_idx, cell in enumerate(row):
                if c_idx >= ncols: break
                cell_text = cell.strip()[:int(col_width // 5)]
                self.draw_text(self.margin_left + c_idx * col_width + 4, self.cursor_y - 10.5,
                               font, 8 if not is_header else 8.5, cell_text, color=txt_color)
            self.cursor_y -= row_height
        self.cursor_y -= 8

    def build(self):
        if self.current_page_ops:
            self.pages.append(self.current_page_ops)

        total_pages = len(self.pages)
        # Add running headers & footers to each page
        for p_idx, page_ops in enumerate(self.pages):
            page_num = p_idx + 1
            # Header
            header_text = "xv6-riscv MLFQ Scheduler -- OS Project Technical Report"
            header_safe = escape_pdf_text(header_text)
            page_ops.append(f"0.50 0.50 0.50 rg BT /F1 7.5 Tf {self.margin_left} 765 Td ({header_safe}) Tj ET")
            page_ops.append(f"0.5 w 0.85 0.85 0.85 RG {self.margin_left} 760 m {self.margin_right} 760 l S")

            # Footer
            footer_text = f"Page {page_num} of {total_pages}"
            footer_safe = escape_pdf_text(footer_text)
            page_ops.append(f"0.5 w 0.85 0.85 0.85 RG {self.margin_left} 35 m {self.margin_right} 35 l S")
            page_ops.append(f"0.50 0.50 0.50 rg BT /F1 8 Tf {self.margin_right - 65} 24 Td ({footer_safe}) Tj ET")
            page_ops.append(f"0.50 0.50 0.50 rg BT /F1 8 Tf {self.margin_left} 24 Td (Operating Systems Group Project -- Part 2: MLFQ) Tj ET")

        # Compile PDF objects
        objects = []
        # obj 1: Catalog
        objects.append("<< /Type /Catalog /Pages 2 0 R >>")
        # obj 2: Pages
        page_refs = " ".join([f"{3 + i*2} 0 R" for i in range(total_pages)])
        objects.append(f"<< /Type /Pages /Kids [{page_refs}] /Count {total_pages} >>")

        # obj fonts
        font_f1 = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        font_f2 = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        font_f3 = "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
        font_f4 = "<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>"

        font_start = 3 + total_pages * 2
        objects.append(font_f1)
        objects.append(font_f2)
        objects.append(font_f3)
        objects.append(font_f4)

        f1_id = font_start
        f2_id = font_start + 1
        f3_id = font_start + 2
        f4_id = font_start + 3

        # Pages and contents
        for i, ops in enumerate(self.pages):
            page_obj_id = 3 + i*2
            content_obj_id = page_obj_id + 1

            stream_data = "\n".join(ops)
            stream_len = len(stream_data.encode('utf-8'))

            page_dict = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_obj_id} 0 R /Resources << /Font << /F1 {f1_id} 0 R /F2 {f2_id} 0 R /F3 {f3_id} 0 R /F4 {f4_id} 0 R >> >> >>"
            content_dict = f"<< /Length {stream_len} >>\nstream\n{stream_data}\nendstream"

            # Insert at correct position
            # We already placed catalog and pages at index 0 and 1
            # We'll assemble full obj array
        
        # Build cleanly
        full_objs = [None, objects[0], objects[1]]
        for i, ops in enumerate(self.pages):
            page_obj_id = 3 + i*2
            content_obj_id = page_obj_id + 1
            stream_data = "\n".join(ops)
            stream_len = len(stream_data.encode('latin1'))

            page_dict = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_obj_id} 0 R /Resources << /Font << /F1 {f1_id} 0 R /F2 {f2_id} 0 R /F3 {f3_id} 0 R /F4 {f4_id} 0 R >> >> >>"
            content_dict = f"<< /Length {stream_len} >>\nstream\n{stream_data}\nendstream"

            full_objs.append(page_dict)
            full_objs.append(content_dict)

        full_objs.append(font_f1)
        full_objs.append(font_f2)
        full_objs.append(font_f3)
        full_objs.append(font_f4)

        # Write output file with byte offsets
        with open(self.filename, 'wb') as f:
            f.write(b"%PDF-1.4\n")
            offsets = [0]
            for idx in range(1, len(full_objs)):
                offset = f.tell()
                offsets.append(offset)
                obj_str = f"{idx} 0 obj\n{full_objs[idx]}\nendobj\n"
                f.write(obj_str.encode('latin1'))

            xref_pos = f.tell()
            f.write(f"xref\n0 {len(full_objs)}\n".encode('latin1'))
            f.write(b"0000000000 65535 f \n")
            for idx in range(1, len(full_objs)):
                f.write(f"{offsets[idx]:010d} 00000 n \n".encode('latin1'))

            trailer = f"trailer\n<< /Size {len(full_objs)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
            f.write(trailer.encode('latin1'))

        print(f"Successfully generated {self.filename} ({total_pages} pages)")


def convert_md_to_pdf(md_path, pdf_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    doc = SimplePDFBuilder(pdf_path)

    # Document Header
    doc.add_title("Multi-Level Feedback Queue (MLFQ) Scheduler in xv6-riscv",
                  "Design, Implementation, Verification & Technical Analysis")

    lines = md_text.splitlines()
    in_code_block = False
    code_lines = []
    in_table = False
    table_rows = []

    for line in lines:
        stripped = line.strip()

        # Code block handling
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                doc.add_code_block(code_lines)
                code_lines = []
            else:
                in_code_block = True
                code_lines = []
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # Table handling
        if stripped.startswith("|") and stripped.endswith("|"):
            if re.match(r"^\|(\s*[-:]+\s*\|)+$", stripped):
                # separator row
                continue
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            table_rows.append(cells)
            in_table = True
            continue
        else:
            if in_table:
                in_table = False
                doc.add_table(table_rows)
                table_rows = []

        if not stripped:
            continue

        # Headings
        if stripped.startswith("# "):
            h_text = stripped[2:].strip()
            if "Table of Contents" in h_text:
                continue
            if "Chapter" in h_text:
                doc.new_page()
            doc.add_heading1(h_text)
        elif stripped.startswith("## "):
            h_text = stripped[3:].strip()
            doc.add_heading1(h_text)
        elif stripped.startswith("### "):
            h_text = stripped[4:].strip()
            doc.add_heading2(h_text)
        elif stripped.startswith("#### "):
            h_text = stripped[5:].strip()
            doc.add_heading3(h_text)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            bullet_text = "• " + stripped[2:].strip()
            doc.add_paragraph(bullet_text)
        elif re.match(r"^\d+\.\s+", stripped):
            doc.add_paragraph(stripped)
        elif stripped == "---":
            doc.ensure_space(15)
            doc.draw_line(doc.margin_left, doc.cursor_y - 5, doc.margin_right, doc.cursor_y - 5, color=(0.8, 0.8, 0.8))
            doc.cursor_y -= 15
        else:
            doc.add_paragraph(stripped)

    if in_table and table_rows:
        doc.add_table(table_rows)

    doc.build()

if __name__ == "__main__":
    md_file = "Project_2/docs/MLFQ_Scheduler_Documentation.md"
    pdf_file = "Project_2/docs/MLFQ_Scheduler_Documentation.pdf"
    if len(sys.argv) > 2:
        md_file = sys.argv[1]
        pdf_file = sys.argv[2]
    convert_md_to_pdf(md_file, pdf_file)
