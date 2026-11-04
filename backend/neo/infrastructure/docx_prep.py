"""
تعديل ملفات التحضير وأوراق العمل (docx) دون المساس بمحتواها التعليمي:
العام الدراسي، واسم المعلم، واليوم والتاريخ في جدول الرأس، وصف جدول المتابعة، وتاريخ ورقة العمل الناقص.

يعمل على XML الأجزاء مباشرة بـ lxml، فيصل إلى ما لا يصله python-docx: مربعات النص (w:txbxContent)،
والرأس والتذييل، وخصائص الغلاف في customXml التي يعيد Word منها كتابة التذييل المربوط (w:dataBinding).
الأجزاء التي لم تتغير تُنسخ بايتًا ببايت، وترتيب المدخلات وتواريخها كما في الأصل، فالناتج حتمي.
"""
from __future__ import annotations

import copy
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from lxml import etree

from neo.domain.weekly_pack import date_text

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


# «2024 / 2025» و«2024-2025» و«2024 – 2025»: سنتان متتاليتان بأي فاصل
YEAR_PAIR = re.compile(r"(20\d\d)(\s*[/\-–—]\s*)(20\d\d)")
# «--/11/2024» و«__/__/2025» و«../11/2024» و«-----11-2024»: تاريخ ناقص اليوم في أوراق العمل
INCOMPLETE_DATE = re.compile(r"(?<!\d)[-_.]{2,8}\s*/?\s*(?:\d{1,2}|[-_.]{2,3})\s*[/\-]\s*20\d\d(?!\d)")
STALE_YEAR = re.compile(r"(?<!\d)(?:2024|2025)(?!\d)")
_LABEL_CLEAN = re.compile(r"[\sـ‎‏:]")
_BIDI = re.compile(r"[\s‎‏]")

TEACHER_LABEL, DATE_LABEL = "اسمالمعلم", "اليوموالتاريخ"
FOLLOW_UP = {"الشعبة": "section", "اليوم": "day", "التاريخ": "date", "الحصة": "period"}


@dataclass(frozen=True)
class PrepFields:
    year_from: int       # بداية العام الدراسي: 2026 لـ 2026-2027
    teacher: str
    day_name: str
    day: date
    section: str
    period: int

    @property
    def date_label(self) -> str:
        return f"{self.day_name} {date_text(self.day)}"


@dataclass
class DocxResult:
    years: int = 0
    teacher: bool = False
    date: bool = False
    follow_up: bool = False
    worksheet_dates: int = 0
    template: str = ""
    parts: list[str] = field(default_factory=list)  # الأجزاء التي تغيّرت

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ------------------------------------------------------------- استبدال على مستوى الفقرة

def _own_texts(p) -> list:
    """عُقد w:t التي تخص هذه الفقرة نفسها، لا فقرات مربعات النص المتداخلة فيها."""
    return [t for t in p.iter(w("t")) if next(t.iterancestors(w("p")), None) is p]


def sub_paragraph(p, pattern: re.Pattern, repl) -> int:
    """يستبدل في نص الفقرة كاملًا ولو توزّع النص على عدة w:t (الرقم «2025» قد يكون في ثلاث عُقد)."""
    nodes = _own_texts(p)
    if not nodes:
        return 0
    texts = [t.text or "" for t in nodes]
    full = "".join(texts)
    matches = [(m.start(), m.end(), repl(m)) for m in pattern.finditer(full)]
    matches = [(s, e, r) for s, e, r in matches if r != full[s:e]]
    if not matches:
        return 0
    bounds, pos = [], 0
    for t in texts:
        bounds.append((pos, pos + len(t)))
        pos += len(t)
    for start, end, new in reversed(matches):  # من الآخر: المواضع السابقة لا تتأثر
        first = True
        for i, (a, b) in enumerate(bounds):
            if b <= start or a >= end or (a == b):
                continue
            s, e = max(start, a) - a, min(end, b) - a
            t = texts[i]
            texts[i] = t[:s] + (new if first else "") + t[e:]
            first = False
        if first:  # المطابقة عند حد فارغ؛ لا يحدث مع أنماط غير فارغة
            continue
    for node, text in zip(nodes, texts):
        if (node.text or "") != text:
            _set_text(node, text)
    return len(matches)


def _set_text(node, text: str) -> None:
    """نص العقدة؛ العقدة التي فرغت تُحذف (يبقى تشغيلها بتنسيقه)، وpreserve فقط حين تحيط بالنص مسافات."""
    if not text:
        node.getparent().remove(node)
        return
    node.text = text
    if text != text.strip():
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def _year_repl(year_from: int):
    def repl(m: re.Match) -> str:
        a, b = int(m.group(1)), int(m.group(3))
        if b == a + 1 and 2015 <= a < year_from:
            return f"{year_from}{m.group(2)}{year_from + 1}"
        return m.group(0)
    return repl


def text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(w("t")))


def _label(el) -> str:
    return _LABEL_CLEAN.sub("", text_of(el))


# ------------------------------------------------------------- الخلايا

def _has_text(el) -> bool:
    return bool(_BIDI.sub("", text_of(el)))


def _run_props(cell):
    """تنسيق خلية العنوان: خصائص أول تشغيل فيه نص، وإلا خصائص علامة الفقرة."""
    for r in cell.iter(w("r")):
        if _has_text(r):
            rpr = r.find(w("rPr"))
            return copy.deepcopy(rpr) if rpr is not None else None
    ppr_rpr = cell.find(f"{w('p')}/{w('pPr')}/{w('rPr')}")
    return copy.deepcopy(ppr_rpr) if ppr_rpr is not None else None


def set_cell_text(cell, text: str, label_cell) -> None:
    """يضع النص في الخلية: في أول تشغيل قائم فيه نص (فيبقى تنسيقه)، وإلا في تشغيل جديد بتنسيق خلية العنوان.
    عنصر التاريخ (w:sdt) الذي فيه تاريخ قديم يُحذف، والفارغ منه يبقى."""
    paras = cell.findall(w("p"))
    if not paras:
        paras = [etree.SubElement(cell, w("p"))]
    for sdt in list(cell.iter(w("sdt"))):
        if re.search(r"\d", text_of(sdt)):
            sdt.getparent().remove(sdt)
    outside = [r for r in cell.iter(w("r"))
               if r.find(w("t")) is not None and not any(a.tag == w("sdt") for a in r.iterancestors())]
    runs = [r for r in outside if _has_text(r)] or outside  # تشغيل مسافات فقط مكانٌ للنص أيضًا
    if runs:
        target, rest = runs[0], runs[1:]
        ts = target.findall(w("t"))
        _set_text(ts[0], text)
        for t in ts[1:]:
            target.remove(t)
        for r in rest:
            for t in r.findall(w("t")):
                r.remove(t)
        return
    run = etree.SubElement(paras[0], w("r"))
    rpr = _run_props(label_cell)
    if rpr is not None:
        run.append(rpr)
    _set_text(etree.SubElement(run, w("t")), text)


def _grid(row) -> list[tuple[int, object]]:
    """(بداية العمود في الشبكة، الخلية) مع مراعاة gridSpan."""
    out, col = [], 0
    for tc in row.findall(w("tc")):
        out.append((col, tc))
        span = tc.find(f"{w('tcPr')}/{w('gridSpan')}")
        col += int(span.get(w("val"))) if span is not None else 1
    return out


def fill_header_table(body, fields: PrepFields, res: DocxResult) -> None:
    tables = [t for t in body if t.tag == w("tbl")]
    if not tables:
        return
    for tr in tables[0].iter(w("tr")):
        cells = tr.findall(w("tc"))
        for i, tc in enumerate(cells[:-1]):
            label = _label(tc)
            if label == TEACHER_LABEL and fields.teacher:
                set_cell_text(cells[i + 1], fields.teacher, tc)
                res.teacher = True
            elif label == DATE_LABEL:
                set_cell_text(cells[i + 1], fields.date_label, tc)
                res.date = True


def fill_follow_up(root, fields: PrepFields, res: DocxResult) -> None:
    values = {"section": fields.section, "day": fields.day_name, "date": date_text(fields.day),
              "period": str(fields.period)}
    for tbl in root.iter(w("tbl")):
        rows = tbl.findall(w("tr"))
        if len(rows) < 2:
            continue
        head = {col: (FOLLOW_UP.get(_label(tc)), tc) for col, tc in _grid(rows[0])}
        if not {"section", "period"} <= {k for k, _ in head.values()}:
            continue
        for col, tc in _grid(rows[1]):
            key, label_cell = head.get(col, (None, None))
            if key:
                set_cell_text(tc, values[key], label_cell)
        res.follow_up = True
        return


# ------------------------------------------------------------- الملف

def _is_word_part(name: str) -> bool:
    return name.startswith("word/") and name.endswith(".xml") and "/ink/" not in name


def _is_custom_item(name: str) -> bool:
    return re.fullmatch(r"customXml/item\d+\.xml", name) is not None


def _serialize(root, original: bytes) -> bytes:
    standalone = b'standalone="yes"' in original[:200]
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True if standalone else None)


# قوالب التحضير المعروفة بعنوان الصف الثالث في جدول الرأس
TEMPLATES = {"الوحدة/المحور/المجال": "الخطة اليومية", "الوحدة": "خطة درس"}


def template_of(root) -> str:
    """القالب من بصمة جدول الرأس، فالقالبان المختلفان يُتحقق من كل منهما بملف."""
    body = root.find(w("body"))
    tables = [t for t in body if t.tag == w("tbl")] if body is not None else []
    if not tables:
        return "بلا جدول رأس"
    labels = [_label(tr.findall(w("tc"))[0]) for tr in tables[0].findall(w("tr")) if tr.findall(w("tc"))]
    unit = next((x for x in labels if x.startswith("الوحدة")), "")
    return TEMPLATES.get(unit, f"قالب آخر ({unit or labels[:1]})")


def prepare_docx(src: Path, dst: Path, fields: PrepFields, worksheet: bool = False) -> DocxResult:
    """ينسخ src إلى dst معدّلًا. لا يُمس src (الأصل في الذاكرة المؤقتة)، فالتكرار ينتج الملف نفسه."""
    res = DocxResult()
    years = _year_repl(fields.year_from)
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        data = {i.filename: zin.read(i.filename) for i in infos}
    for name, raw in data.items():
        if not (_is_word_part(name) or _is_custom_item(name)):
            continue
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError:
            continue
        changed = 0
        if _is_custom_item(name):  # خصائص الغلاف: PublishDate وأخواتها نص خالص
            for el in root.iter():
                if isinstance(el.tag, str) and el.text and YEAR_PAIR.search(el.text):
                    new = YEAR_PAIR.sub(years, el.text)
                    if new != el.text:
                        el.text, changed = new, changed + 1
            res.years += changed
        else:
            for p in root.iter(w("p")):
                n = sub_paragraph(p, YEAR_PAIR, years)
                res.years += n
                changed += n
                if worksheet:
                    k = sub_paragraph(p, INCOMPLETE_DATE, lambda m: date_text(fields.day))
                    res.worksheet_dates += k
                    changed += k
            if name == "word/document.xml":
                res.template = "ورقة عمل" if worksheet else template_of(root)
                if not worksheet:
                    body = root.find(w("body"))
                    before = (res.teacher, res.date, res.follow_up)
                    fill_header_table(body, fields, res)
                    fill_follow_up(root, fields, res)
                    changed += (res.teacher, res.date, res.follow_up) != before
        if changed:
            data[name] = _serialize(root, raw)
            res.parts.append(name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zout:
        for info in infos:  # الترتيب والتواريخ وطريقة الضغط كما في الأصل
            zout.writestr(info, data[info.filename], compress_type=info.compress_type)
    tmp.replace(dst)
    return res


def stale_years(path: Path) -> list[str]:
    """فحص نصي شامل لأجزاء word/ وcustomXml: أي 2024 أو 2025 باقٍ في النص (لا في معرّفات السمات)."""
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not (_is_word_part(name) or name.startswith("customXml/")) or not name.endswith(".xml"):
                continue
            try:
                root = etree.fromstring(z.read(name))
            except etree.XMLSyntaxError:
                continue
            if name.startswith("customXml/"):
                texts = [el.text for el in root.iter() if isinstance(el.tag, str) and el.text]
            else:
                texts = [text_of_own(p) for p in root.iter(w("p"))]
                texts += [el.text or "" for el in root.iter(w("instrText"))]
            for text in texts:
                for m in STALE_YEAR.finditer(text):
                    snippet = text if len(text) <= 80 else text[max(0, m.start() - 30):m.end() + 15]
                    out.append(f"{name}: {snippet.strip()}")
    return out


def paragraphs(path: Path) -> list[str]:
    """نصوص فقرات المستند (لاستخراج تدريبات كتاب الطالب)."""
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    return [t for t in (text_of_own(p) for p in root.iter(w("p"))) if t.strip()]


def text_of_own(p) -> str:
    return "".join(t.text or "" for t in _own_texts(p))
