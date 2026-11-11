"""
صف الرسالة الأسبوعية ملفَّ وورد فيه جدول بأعمدة نموذج المدرسة، لا نصًّا مفصولًا بعلامات Tab.

يُبنى الملف من XML مباشرة (بلا قالب)، وتواريخ مدخلات الأرشيف ثابتة، فالمدخلات نفسها تعطي الملف نفسه بايتًا ببايت
ويبقى «لم يتغير عن التشغيل السابق» صادقًا. الجدول من اليمين إلى اليسار، والصفحة أفقية، وترويسته مظلّلة وتتكرر.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FONT = "Sakkal Majalla"
SIZE = 28            # نصف نقطة: 14pt
HEADER_FILL = "D9D9D9"
# عرض الأعمدة بالـ twip بترتيب MESSAGE_HEADER؛ مجموعها عرض الصفحة الأفقية بعد الهوامش
WIDTHS = (1100, 3300, 1500, 5300, 1900, 1500)
# أعمدة يُقسم نصها أسطرًا داخل الخلية ليقرأها ولي الأمر بلا ازدحام: الموضوعات بالفاصلة، والواجبات بالفاصلة المنقوطة
SPLIT = {1: "، ", 3: "؛ "}
_FIXED_TIME = (2020, 1, 1, 0, 0, 0)
# رقم أو مدى أو شعبة أو رمز لاتيني، مع علامات الاتجاه الملاصقة: «‎1–4» «12/2» «20a‏»
_LATIN = re.compile(r"[‎‏]*[0-9A-Za-z]+(?:[–\-/.][0-9A-Za-z]+)*[‎‏]*")

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _sub(parent, tag: str, **attrs):
    el = etree.SubElement(parent, w(tag))
    for k, v in attrs.items():
        el.set(w(k), str(v))
    return el


def segments(text: str) -> list[tuple[str, bool]]:
    """(نص، عربي؟): الأرقام والمدى والشعبة («1–4» «154–168» «12/2» «20a») قطع بلا w:rtl، وإلا قلبها وورد
    في السطر العربي إلى «4–1» و«2/12» ولو سبقتها علامة LRM."""
    out, pos = [], 0
    for m in _LATIN.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], True))
        out.append((m.group(0), False))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], True))
    return out


def _run(p, text: str, bold: bool, rtl: bool) -> None:
    r = _sub(p, "r")
    rpr = _sub(r, "rPr")
    _sub(rpr, "rFonts", ascii=FONT, hAnsi=FONT, cs=FONT)
    if bold:
        _sub(rpr, "b")
        _sub(rpr, "bCs")
    _sub(rpr, "sz", val=SIZE)
    _sub(rpr, "szCs", val=SIZE)
    if rtl:
        _sub(rpr, "rtl")
    t = _sub(r, "t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _para(parent, text: str, bold: bool = False, center: bool = False) -> None:
    p = _sub(parent, "p")
    ppr = _sub(p, "pPr")
    _sub(ppr, "bidi")
    _sub(ppr, "spacing", before=0, after=0)
    _sub(ppr, "jc", val="center" if center else "left")  # في الفقرة bidi «left» هي البداية: يمين الصفحة
    for chunk, rtl in segments(text):
        _run(p, chunk, bold, rtl)


def cell_lines(index: int, text: str) -> list[str]:
    sep = SPLIT.get(index)
    parts = [x.strip() for x in text.split(sep)] if sep else [text.strip()]
    return [x for x in parts if x] or [""]


def _cell(tr, index: int, text: str, header: bool) -> None:
    tc = _sub(tr, "tc")
    tcpr = _sub(tc, "tcPr")
    _sub(tcpr, "tcW", w=WIDTHS[index], type="dxa")
    if header:
        _sub(tcpr, "shd", val="clear", color="auto", fill=HEADER_FILL)
    _sub(tcpr, "vAlign", val="center")
    for line in (cell_lines(index, text) if not header else [text]):
        _para(tc, line, bold=header, center=header or index in (0, 2, 4))


def document_xml(header: list[str] | tuple[str, ...], row: list[str]) -> bytes:
    doc = etree.Element(w("document"), nsmap={"w": W_NS})
    body = _sub(doc, "body")
    tbl = _sub(body, "tbl")
    tblpr = _sub(tbl, "tblPr")
    _sub(tblpr, "bidiVisual")
    _sub(tblpr, "tblW", w=sum(WIDTHS), type="dxa")
    _sub(tblpr, "jc", val="center")
    borders = _sub(tblpr, "tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _sub(borders, side, val="single", sz=8, space=0, color="000000")
    _sub(tblpr, "tblLayout", type="fixed")
    mar = _sub(tblpr, "tblCellMar")
    for side in ("top", "bottom"):
        _sub(mar, side, w=60, type="dxa")
    for side in ("left", "right"):
        _sub(mar, side, w=100, type="dxa")
    grid = _sub(tbl, "tblGrid")
    for width in WIDTHS:
        _sub(grid, "gridCol", w=width)
    head = _sub(tbl, "tr")
    _sub(_sub(head, "trPr"), "tblHeader")
    for i, title in enumerate(header):
        _cell(head, i, title, header=True)
    tr = _sub(tbl, "tr")
    _sub(_sub(tr, "trPr"), "cantSplit")
    for i, text in enumerate(row):
        _cell(tr, i, text, header=False)
    _para(body, "")  # الجدول لا يكون آخر عنصر في الجسم
    sect = _sub(body, "sectPr")
    _sub(sect, "pgSz", w=16838, h=11906, orient="landscape")
    _sub(sect, "pgMar", top=720, right=720, bottom=720, left=720, header=0, footer=0, gutter=0)
    _sub(sect, "bidi")
    return etree.tostring(doc, xml_declaration=True, encoding="UTF-8", standalone=True)


def write_message(path: Path, header: list[str] | tuple[str, ...], row: list[str]) -> None:
    if len(row) != len(header) or len(header) != len(WIDTHS):
        raise ValueError(f"صف الرسالة {len(row)} خلايا والترويسة {len(header)}، والمتوقع {len(WIDTHS)}")
    parts = (("[Content_Types].xml", _CONTENT_TYPES.encode()), ("_rels/.rels", _RELS.encode()),
             ("word/document.xml", document_xml(header, row)))
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    tmp.replace(path)
