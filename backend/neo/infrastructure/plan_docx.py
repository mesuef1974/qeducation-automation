"""
خطة التحضير اليومية بقالب المدرسة: تُستنسخ خطة درس مجاور (الجدول الأول بصفوفه المعروفة) وتُملأ خلاياها بنصوص جديدة
فتبقى الترويسة والكفايات والقيم والمعايير المهنية واستراتيجيات التعلم والتأمل كما في خطط المعلم.
صفوف الجدول تُعرف بعنوان عمودها الأول لا برقمها، فيصمد الملء أمام اختلاف بسيط بين القوالب.
"""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


class PlanTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Block:
    """صف أنشطة: الهدف في العمود الأول، والنشاط في الأعمدة 1-3، والتقويم البنائي في 4-5."""
    objective: str
    title: str                         # عنوان النشاط في أول سطر: «<العنوان>: الاستراتيجية .. الكفاية .. القيمة ..»
    activity: tuple[str, ...]          # باقي الأسطر
    assessment: tuple[str, ...] = ()
    strategy: str = "التعلم الثنائي"   # من قوائم القالب المنسدلة حرفيًا
    competency: str = "التفكير الابداعي والتفكير الناقد"
    value: str = "الايجابية والمثابرة"
    minutes: int = 10                  # عمود «الزمن»


@dataclass(frozen=True)
class PlanContent:
    unit: str
    title: str
    outcomes: tuple[str, ...]
    terms: str
    main_resources: tuple[str, ...]
    support_resources: tuple[str, ...]
    warmup: tuple[str, ...]
    blocks: tuple[Block, ...]
    closing: tuple[str, ...]
    homework: str


def lesson_title(doc) -> str:
    row = _row(doc.tables[0], "الوحدة")
    cells = _cells(row)
    return " ".join(cells[-1].text.split()) if len(cells) >= 4 else ""


def _cells(row):
    seen, out = set(), []
    for c in row.cells:
        if id(c._tc) not in seen:
            seen.add(id(c._tc))
            out.append(c)
    return out


def _row(table, label: str):
    for row in table.rows:
        first = " ".join(row.cells[0].text.split())
        if first.startswith(label):
            return row
    raise PlanTemplateError(f"القالب بلا صف «{label}»")


def set_cell(cell, lines) -> None:
    """يملأ الخلية سطرًا لكل فقرة بتنسيق أول مقطع من الفقرة المقابلة (أو آخر فقرة)."""
    lines = [lines] if isinstance(lines, str) else list(lines)
    paras = cell.paragraphs
    if not paras:  # خلية مدموجة رأسيًا بلا فقرات: لا شيء يُكتب فيها
        return
    while len(paras) < len(lines):
        clone = deepcopy(paras[-1]._p)
        paras[-1]._p.addnext(clone)
        paras = cell.paragraphs
    for p in paras[len(lines):]:
        p._p.getparent().remove(p._p)
    for p, text in zip(cell.paragraphs, lines):
        runs = p.runs
        if not runs:
            p.add_run()
            runs = p.runs
        runs[0].text = text
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
        if p._p.find(qn("w:hyperlink")) is not None:
            for h in p._p.findall(qn("w:hyperlink")):
                p._p.remove(h)


def _set_dropdown(sdt, value: str) -> None:
    allowed = [li.get(qn("w:displayText")) for li in sdt.iter(qn("w:listItem")) if li.get(qn("w:displayText"))]
    if value not in allowed:
        raise PlanTemplateError(f"«{value}» ليست من خيارات القائمة: {'، '.join(allowed)}")
    texts = list(sdt.find(qn("w:sdtContent")).iter(qn("w:t")))
    texts[0].text = value
    for t in texts[1:]:
        t.text = ""


def _fill_activity(cell, block: "Block") -> None:
    """السطر الأول بنية القالب: عنوان النشاط ثم قوائم الاستراتيجية والكفاية والقيمة المنسدلة؛ الباقي نص حر."""
    first = cell.paragraphs[0]._p
    sdts = first.findall(qn("w:sdt"))
    if len(sdts) != 3:
        set_cell(cell, [f"{block.title}: الاستراتيجية {block.strategy} الكفاية {block.competency} القيمة {block.value}",
                        *block.activity])
        return
    runs = first.findall(qn("w:r"))
    label = next(i for i, r in enumerate(runs) if "الاستراتيجية" in "".join(t.text or "" for t in r.iter(qn("w:t"))))
    for r in runs[1:label]:
        first.remove(r)
    runs[0].find(qn("w:t")).text = f"{block.title}: "
    for sdt, value in zip(sdts, (block.strategy, block.competency, block.value)):
        _set_dropdown(sdt, value)
    rest = list(block.activity) or [""]
    body = cell.paragraphs[1:]
    while len(body) < len(rest):
        clone = deepcopy(body[-1]._p if body else first)
        (body[-1]._p if body else first).addnext(clone)
        body = cell.paragraphs[1:]
    for p in body[len(rest):]:
        p._p.getparent().remove(p._p)
    for p, text in zip(cell.paragraphs[1:], rest):
        for extra in p._p.findall(qn("w:sdt")):  # قوائم القالب القديمة في بقية الأسطر
            p._p.remove(extra)
        runs = p.runs or [p.add_run()]
        runs[0].text = text
        for r in runs[1:]:
            r._r.getparent().remove(r._r)


def _activity_rows(table):
    """صفوف الأنشطة: بين «أهداف التعلم» و«الغلق الختامي»."""
    rows = list(table.rows)
    start = next(i for i, r in enumerate(rows) if " ".join(r.cells[0].text.split()).startswith("أهداف التعلم")) + 1
    end = next(i for i, r in enumerate(rows) if " ".join(r.cells[0].text.split()).startswith("الغلق"))
    return rows[start:end]


def fill(template: Path, out: Path, c: PlanContent) -> None:
    doc = Document(str(template))
    t = doc.tables[0]
    unit = _cells(_row(t, "الوحدة"))
    set_cell(unit[1], c.unit)
    set_cell(unit[-1], c.title)
    set_cell(_cells(_row(t, "نتاجات التعلم"))[1], list(c.outcomes) or [""])
    set_cell(_cells(_row(t, "المصطلحات"))[1], c.terms)
    res = _cells(_row(t, "مصادر التعلم الرئيسة"))
    set_cell(res[1], list(c.main_resources))
    set_cell(res[-1], list(c.support_resources))
    warm = list(t.rows)
    idx = next(i for i, r in enumerate(warm) if " ".join(r.cells[0].text.split()) == "التهيئة")
    set_cell(_cells(warm[idx + 1])[0], list(c.warmup))
    rows = _activity_rows(t)
    if not rows:
        raise PlanTemplateError("القالب بلا صفوف أنشطة")
    while len(rows) < len(c.blocks):  # خطط الدروس الأقصر: يُستنسخ آخر صف نشاط بتنسيقه
        clone = deepcopy(rows[-1]._tr)
        rows[-1]._tr.addnext(clone)
        rows = _activity_rows(t)
    for row, block in zip(rows, c.blocks):
        cells = _cells(row)
        set_cell(cells[0], ["في نهاية الحصة على الطالب أن يكون قادراً على أن:", block.objective]
                 if row is rows[0] else [block.objective])
        _fill_activity(cells[1], block)
        if cells[-1].paragraphs and "".join(cells[-1].text.split()).isdigit():
            set_cell(cells[-1], str(block.minutes))  # عمود «الزمن»: يُستبدل رقم القالب
        if len(cells) > 2 and block.assessment:
            set_cell(cells[2], list(block.assessment))
    for row in rows[len(c.blocks):]:  # صفوف فائضة في القالب تُفرَّغ
        for cell in _cells(row):
            set_cell(cell, [""])
    set_cell(_cells(_row(t, "الغلق"))[1], list(c.closing))
    set_cell(_cells(_row(t, "الواجب"))[1], c.homework)
    for row in list(doc.tables[2].rows)[1:4]:  # جدول التأمل يُملأ بعد التدريس: يُفرَّغ مما ورثه عن الدرس المجاور
        for cell in _cells(row):
            if cell.text.strip():
                set_cell(cell, [""])
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))


def set_outcomes(path: Path, outcomes: list[tuple[str, str]]) -> None:
    """يكتب النتاجات المربوطة فعلًا بالدرس (الرمز والنص) في صف «نتاجات التعلم»."""
    doc = Document(str(path))
    set_cell(_cells(_row(doc.tables[0], "نتاجات التعلم"))[1], [f"{code} {text}" for code, text in outcomes])
    doc.save(str(path))
