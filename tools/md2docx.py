# 把小飞鱼画板的介绍（Markdown 子集）转成 Word
"""支持：`#`/`##`/`###` 标题、段落、`- ` 列表、`|` 表格、代码块、
`**粗体**`、行内代码、图片、`---` 分隔线。

用 python-docx 生成，中文字体显式设 eastAsia，否则 Word 里中文会退回宋体。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("介绍.md")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("小飞鱼画板介绍.docx")
BASE = SRC.parent

CN_FONT = "微软雅黑"
MONO_FONT = "Consolas"
INK = RGBColor(0x22, 0x22, 0x22)
ACCENT = RGBColor(0x1F, 0x5F, 0x8B)
MUTED = RGBColor(0x77, 0x77, 0x77)


def set_cn(run, font=CN_FONT):
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        rfonts.set(qn(attr), font)


def clean(text: str) -> str:
    """去掉标题里的 markdown 记号（标题不走富文本解析）。

    反引号用 chr(96) 写：直接写会经过 PowerShell 的转义，被悄悄吃掉。
    """
    return text.replace("**", "").replace(chr(96), "") 


def add_rich(par, text, size=10.5, color=INK, bold=False):
    """把 **粗体** 和 `代码` 拆成不同 run。"""
    for piece in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            r = par.add_run(piece[2:-2])
            r.bold = True
            set_cn(r)
            r.font.size = Pt(size)
            r.font.color.rgb = color
        elif piece.startswith("`") and piece.endswith("`"):
            r = par.add_run(piece[1:-1])
            set_cn(r, MONO_FONT)
            r.font.size = Pt(size - 0.5)
            r.font.color.rgb = ACCENT
        else:
            r = par.add_run(piece)
            set_cn(r)
            r.font.size = Pt(size)
            r.font.color.rgb = color
            if bold:
                r.bold = True


def style_doc(doc):
    st = doc.styles["Normal"]
    st.font.name = CN_FONT
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    for name, size, color in (("Heading 1", 17, ACCENT),
                              ("Heading 2", 13.5, INK),
                              ("Heading 3", 11.5, INK)):
        s = doc.styles[name]
        s.font.name = CN_FONT
        s.font.size = Pt(size)
        s.font.color.rgb = color
        s.font.bold = True
        s.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)


def add_table(doc, rows):
    head, body = rows[0], rows[1:]
    t = doc.add_table(rows=1, cols=len(head))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, cell in enumerate(head):
        p = t.rows[0].cells[i].paragraphs[0]
        add_rich(p, cell, size=10, bold=True)
    for row in body:
        cells = t.add_row().cells
        for i, cell in enumerate(row[:len(head)]):
            add_rich(cells[i].paragraphs[0], cell, size=10)
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
    # 行不许跨页断开；表头行跨页时重复（否则第二页只剩一条空蓝带）
    for idx, row in enumerate(t.rows):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(trPr.makeelement(qn("w:cantSplit"), {}))
        if idx == 0:
            trPr.append(trPr.makeelement(qn("w:tblHeader"), {}))
    return t


def add_code(doc, lines):
    for i, ln in enumerate(lines):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.left_indent = Cm(0.5)
        # 代码块用一个浅底：靠段落底纹实现
        pPr = p._element.get_or_add_pPr()
        shd = pPr.makeelement(qn("w:shd"), {
            qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): "F4F1EA"})
        pPr.append(shd)
        if i < len(lines) - 1:
            p.paragraph_format.keep_with_next = True
        r = p.add_run(ln if ln else " ")
        set_cn(r, MONO_FONT)
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_image(doc, path: Path, caption: str = ""):
    if not path.exists():
        return
    # 同时限宽和限高：竖图（人物、树枝）只限宽会顶到一米高，
    # 把下一页的内容全挤走，中间留一大片白。
    from PIL import Image
    with Image.open(path) as im:
        wpx, hpx = im.size
    max_w, max_h = 13.5, 8.5         # 厘米；竖图太高会把图注挤到下一页
    scale = min(max_w / wpx, max_h / hpx)
    doc.add_picture(str(path), width=Cm(wpx * scale))
    pic_par = doc.paragraphs[-1]
    pic_par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pic_par.paragraph_format.keep_with_next = True   # 图注别跟图分家
    if caption:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(caption)
        set_cn(r)
        r.font.size = Pt(9)
        r.font.color.rgb = MUTED


def convert(src: Path, out: Path):
    md = src.read_text(encoding="utf-8").splitlines()
    doc = Document()
    style_doc(doc)
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.4)
    sec.top_margin = sec.bottom_margin = Cm(2.2)

    i, n = 0, len(md)
    first_h1 = True
    while i < n:
        line = md[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            j = i + 1
            buf = []
            while j < n and not md[j].strip().startswith("```"):
                buf.append(md[j])
                j += 1
            add_code(doc, buf)
            i = j + 1
            continue
        if s == "---":
            p = doc.add_paragraph()
            pPr = p._element.get_or_add_pPr()
            bdr = pPr.makeelement(qn("w:pBdr"), {})
            bottom = bdr.makeelement(qn("w:bottom"), {
                qn("w:val"): "single", qn("w:sz"): "6",
                qn("w:space"): "1", qn("w:color"): "CCCCCC"})
            bdr.append(bottom)
            pPr.append(bdr)
            i += 1
            continue
        if s.startswith("# "):
            if first_h1:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(s[2:])
                set_cn(r)
                r.font.size = Pt(26)
                r.bold = True
                r.font.color.rgb = ACCENT
                first_h1 = False
            else:
                doc.add_heading(s[2:], level=1)
            i += 1
            continue
        if s.startswith("## "):
            doc.add_heading(clean(s[3:]), level=1)
            i += 1
            continue
        if s.startswith("### "):
            doc.add_heading(clean(s[4:]), level=2)
            i += 1
            continue
        m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if m:
            add_image(doc, BASE / m.group(2), m.group(1))
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            j = i
            while j < n and md[j].strip().startswith("|"):
                cells = [c.strip() for c in md[j].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                j += 1
            if rows:
                add_table(doc, rows)
                doc.add_paragraph().paragraph_format.space_after = Pt(2)
            i = j
            continue
        if s.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            add_rich(p, s[2:])
            i += 1
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        add_rich(p, s)
        i += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


if __name__ == "__main__":
    path = convert(SRC, OUT)
    print("写好", path.name)
