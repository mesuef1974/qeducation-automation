"""
مصمّم درس المراجعة: يولّد مجلد مواصفة كاملًا (lesson.json + عرض pptx + ورقة عمل docx + خطة docx) من بنك المراجعة
بلا شبكة ولا نموذج لغوي، ثم يُعاين المعلم المخرج ويعتمده قبل أي كتابة على المنصة (neo_lesson --apply).
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from neo.domain import assessment, review_bank


@dataclass(frozen=True)
class ReviewRequest:
    lms_id: int
    academic_year: str
    unit_title: str
    day: date
    period: int
    grade: str = "الصف العاشر"
    term: str = "الفصل الأول"
    before_title: str = ""
    lesson_title: str = ""

    @property
    def title(self) -> str:
        return self.lesson_title or f"مراجعة واختبار {self.unit_title}"


def _rtl_para(p, align=PP_ALIGN.RIGHT):
    p.alignment = align
    p._p.get_or_add_pPr().set("rtl", "1")


def _slide(prs, title: str, lines: list[str], size: int = 24):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box = s.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12.1), Inches(1.0))
    p = box.text_frame.paragraphs[0]
    p.text = title
    p.font.size, p.font.bold, p.font.color.rgb = Pt(36), True, RGBColor(0x1F, 0x4E, 0x79)
    _rtl_para(p)
    body = s.shapes.add_textbox(Inches(0.6), Inches(1.6), Inches(12.1), Inches(5.4))
    tf = body.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(size)
        p.space_after = Pt(10)
        _rtl_para(p)


def build_deck(req: ReviewRequest, path: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    _slide(prs, req.title, [req.unit_title, "عرض مراجعة: مهارات الوحدة ثم تقييم ذاتي التصحيح"], 28)
    _slide(prs, "أهداف الدرس", [f"• أراجع: {s}" for s in review_bank.SKILLS], 22)
    for skill in review_bank.SKILLS:
        items = review_bank.by_skill(skill)
        mcq = next(i for i in items if i.choices)
        lines = [mcq.text, "", f"الحل: {mcq.work}", f"الإجابة: {mcq.choices[0]}"]
        _slide(prs, skill, lines, 26)
        tf = next((i for i in items if not i.choices), None)
        if tf:
            _slide(prs, f"{skill}: صح أم خطأ؟", [tf.text, "", "فكّر ثم ناقش زميلك."], 28)
    _slide(prs, "تقييم الدرس", ["أجب عن أسئلة التقييم الذاتي في المنصة", "نتيجتك تحدد المهارات التي تحتاج مراجعة إضافية"], 28)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))


def _doc_rtl(doc: Document):
    for p in doc.paragraphs:
        _para_rtl(p)


def _para_rtl(p):
    ppr = p._p.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.append(OxmlElement("w:bidi"))
    for r in p.runs:
        rpr = r._r.get_or_add_rPr()
        if rpr.find(qn("w:rtl")) is None:
            rpr.append(OxmlElement("w:rtl"))


def build_worksheet(req: ReviewRequest, path: Path) -> None:
    doc = Document()
    doc.add_heading(f"ورقة عمل: {req.title}", 1)
    doc.add_paragraph("الاسم: ....................................   الشعبة: ..........")
    n = 0
    for skill in review_bank.SKILLS:
        doc.add_heading(skill, 2)
        for it in review_bank.by_skill(skill):
            n += 1
            doc.add_paragraph(f"{n}) {it.text}")
            if it.choices:
                for letter, c in zip("أبجد", it.rotated(n)[0]):
                    doc.add_paragraph(f"    {letter}. {c}")
            else:
                doc.add_paragraph("    صح  /  خطأ")
    doc.add_page_break()
    doc.add_heading("مفتاح الإجابة (للمعلم)", 1)
    n = 0
    for skill in review_bank.SKILLS:
        for it in review_bank.by_skill(skill):
            n += 1
            ans = (f"{'أبجد'[it.rotated(n)[1]]}. {it.choices[0]}" if it.choices else ("صح" if it.truth else "خطأ"))
            doc.add_paragraph(f"{n}) {ans}" + (f" — {it.work}" if it.work else ""))
    _doc_rtl(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def build_plan(req: ReviewRequest, path: Path) -> None:
    doc = Document()
    doc.add_heading(f"خطة الدرس: {req.title}", 1)
    rows = (
        ("المستوى", f"{req.grade} - {req.term}"),
        ("الوحدة", req.unit_title),
        ("التاريخ والحصة", f"{req.day.isoformat()} - الحصة {req.period}"),
        ("أهداف الدرس", "؛ ".join(f"أراجع {s}" for s in review_bank.SKILLS)),
        ("التهيئة (5 د)", "سؤالان سريعان من أصعب مهارات الوحدة على السبورة، يجيب عنهما الطلاب فرديًا."),
        ("العرض (20 د)", "عرض المراجعة: مثال محلول لكل مهارة ثم سؤال صح/خطأ للنقاش الثنائي."),
        ("التطبيق (15 د)", "ورقة العمل في مجموعات ثنائية، والمعلم يتجول ويشخّص الأخطاء الشائعة."),
        ("التقويم الختامي (5 د)", f"تقييم الدرس الذاتي التصحيح ({len(review_bank.review_quiz())} سؤالًا) على المنصة."),
        ("الواجب", "حل بنود ورقة العمل التي لم تُنجز في الحصة."),
    )
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in rows:
        c = t.add_row().cells
        c[0].text, c[1].text = k, v
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                _para_rtl(p)
    _doc_rtl(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def _objectives_html() -> str:
    items = "".join(f"<li>أراجع {s}.</li>" for s in review_bank.SKILLS)
    return f"<h3>أهداف الدرس</h3><ul>{items}</ul>"


def _steps_html() -> str:
    return ("<h3>سير الحصة</h3><ol><li>تهيئة: سؤالان سريعان.</li><li>عرض المراجعة ومناقشة بنود صح/خطأ.</li>"
            "<li>ورقة العمل في مجموعات.</li><li>التقييم الذاتي التصحيح.</li></ol>")


def design(req: ReviewRequest, out: Path) -> Path:
    """يكتب المجلد ويعيد مسار lesson.json. يُعاد استدعاؤه بأمان: يستبدل ملفاته المولّدة وحدها."""
    out.mkdir(parents=True, exist_ok=True)
    build_deck(req, out / "deck.pptx")
    build_worksheet(req, out / "worksheet.docx")
    build_plan(req, out / "plan.docx")
    quiz = assessment.to_text(review_bank.review_quiz())
    spec = {
        "class": req.lms_id, "academic_year": req.academic_year, "title": req.title,
        "description": f"مراجعة شاملة لمهارات {req.unit_title} بمثال محلول لكل مهارة وورقة عمل وتقييم ذاتي التصحيح.",
        "date": req.day.isoformat(), "period": req.period, "grade": req.grade, "term": req.term,
        "before_title": req.before_title,
        "tags": ["مراجعة", "معادلات تربيعية", "متباينات تربيعية", "المميز", "إكمال المربع", "الدائرة"],
        "pages": [{"name": "أهداف الدرس", "html": _objectives_html()}, {"name": "سير الحصة", "html": _steps_html()}],
        "decks": [{"title": "عرض المراجعة", "file": "deck.pptx"}],
        "quiz_name": f"تقييم {req.title}", "quiz": quiz,
        "notes": [
            {"label": f"التحضير - {req.title}", "file": "plan.docx"},
            {"label": f"ورقة عمل - {req.title}", "file": "worksheet.docx"},
            {"label": f"عرض الدرس - {req.title}", "file": "deck.pptx"},
        ],
    }
    path = out / "lesson.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
