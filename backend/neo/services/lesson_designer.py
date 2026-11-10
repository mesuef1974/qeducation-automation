"""
مصمّم درس المراجعة: يولّد مجلد مواصفة كاملًا (lesson.json + عرض pptx + ورقة عمل docx + خطة docx) من بنك المراجعة
بلا شبكة ولا نموذج لغوي، ثم يُعاين المعلم المخرج ويعتمده قبل أي كتابة على المنصة (neo_lesson --apply).
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pptx import Presentation

from neo.domain import assessment, review_bank
from neo.domain.review_bank import ltr
from neo.infrastructure import deck_pptx, plan_docx


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
    deck_template: Path | None = None   # عرض درس مجاور؛ فارغ = يُستنتج من عنوان الدرس المجاور
    plan_template: Path | None = None   # خطة درس مجاور
    cache_dir: Path | None = None       # أصول المنصة المنزَّلة (prep_cache)
    outcome_prefixes: tuple[str, ...] = ("10.2.",)  # نتاجات الوحدة تُختار من المتاح للصف
    points: dict = field(default_factory=dict)       # {"points": 5, "game": "...", "notification": "Popup"}
    show: bool = True                                # يُظهر الدرس بعد اكتماله (ثم تحقق الرؤية)

    @property
    def title(self) -> str:
        return self.lesson_title or f"مراجعة واختبار {self.unit_title}"


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
            doc.add_paragraph(f"{n}) {ltr(it.text)}")
            if it.choices:
                for letter, c in zip("أبجد", it.rotated(n)[0]):
                    doc.add_paragraph(f"    {letter}. {ltr(c)}")
            else:
                doc.add_paragraph("    صح  /  خطأ")
    doc.add_page_break()
    doc.add_heading("مفتاح الإجابة (للمعلم)", 1)
    n = 0
    for skill in review_bank.SKILLS:
        for it in review_bank.by_skill(skill):
            n += 1
            ans = (f"{'أبجد'[it.rotated(n)[1]]}. {it.choices[0]}" if it.choices else ("صح" if it.truth else "خطأ"))
            doc.add_paragraph(ltr(f"{n}) {ans}" + (f" — {it.work}" if it.work else "")))
    _doc_rtl(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def _hint(req: ReviewRequest) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", req.before_title).strip()


def find_templates(req: ReviewRequest) -> tuple[Path, Path]:
    """عرض وخطة درس مجاور من أصول المنصة المنزَّلة، بعنوان الدرس المجاور (الأحدث أولًا)."""
    if req.deck_template and req.plan_template:
        return req.deck_template, req.plan_template
    hint = _hint(req)
    if not (req.cache_dir and hint):
        raise plan_docx.PlanTemplateError("حدّد قالب الخطة والعرض، أو الدرس المجاور (--before) وأصول المنصة")
    root = req.cache_dir / "files"
    decks = sorted(root.glob("*/*.pptx"), key=lambda f: f.stat().st_mtime, reverse=True)
    plans = sorted(root.glob("*/*.docx"), key=lambda f: f.stat().st_mtime, reverse=True)
    deck = req.deck_template or next((f for f in decks if _deck_matches(f, hint)), None)
    plan = req.plan_template or next((f for f in plans if _plan_matches(f, hint)), None)
    if not deck or not plan:
        raise plan_docx.PlanTemplateError(f"لا خطة/عرض منزَّل لدرس مجاور «{hint}»؛ شغّل حزمة تحضيره أولًا")
    return deck, plan


def _deck_matches(f: Path, hint: str) -> bool:
    try:
        prs = Presentation(str(f))
        return len(prs.slides) >= 18 and deck_pptx.master_title(prs).startswith(hint)
    except Exception:  # noqa: BLE001 - ملف تالف لا يوقف البحث
        return False


def _plan_matches(f: Path, hint: str) -> bool:
    try:
        return plan_docx.lesson_title(Document(str(f))).startswith(hint)
    except Exception:  # noqa: BLE001
        return False


GROUPS = ((0, 4, "2.1 إلى 2.4", "يحل معادلات تربيعية بيانيًا وبالتحليل والجذور",
           ("التعلم الثنائي", "التفكير الابداعي والتفكير الناقد", 15)),
          (4, 7, "2.5 إلى 2.7", "يحل معادلات تربيعية بإكمال المربع والقانون العام والمعادلات النسبية",
           ("حل المشكلات", "الكفاية العددية", 10)),
          (7, 10, "2.8 إلى 2.10", "يحل أنظمة ومتباينات تربيعية ويكتب معادلة الدائرة",
           ("التعلم الثنائي", "التواصل", 10)))


def build_plan(req: ReviewRequest, template: Path, path: Path, outcomes: tuple[str, ...] = ()) -> None:
    blocks = []
    for lo, hi, lessons, objective, (strategy, competency, minutes) in GROUPS:
        names = review_bank.SKILLS[lo:hi]
        blocks.append(plan_docx.Block(minutes=minutes, objective=objective, title=f"مراجعة دروس الوحدة ({lessons})", activity=(
            f"- يعرض المعلم مثالًا محلولًا لكل مهارة: {'، '.join(names)}.",
             "- يطلب من الثنائيات حل بند صح/خطأ ثم مناقشة الإجابة مع الجميع.",
             "- يقدم المعلم التغذية الراجعة المناسبة.",
             "- يتوصل الطلاب إلى إتقان المهارات ومعالجة الأخطاء الشائعة."),
            assessment=("أسئلة صح/خطأ على الشرائح وملاحظة حلول الطلاب",), strategy=strategy, competency=competency))
    plan_docx.fill(template, path, plan_docx.PlanContent(
        unit=req.unit_title, title=req.title, outcomes=outcomes,
        terms="المعادلة التربيعية / المميز / إكمال المربع / المتباينة التربيعية / معادلة الدائرة",
        main_resources=("دليل المعلم: مراجعة الوحدة الثانية",),
        support_resources=("ورقة العمل وعرض المراجعة والتقييم الذاتي على منصة تعليم قطر",),
        warmup=("الاستراتيجية: يعرض المعلم سؤالين سريعين من أصعب مهارات الوحدة (التحليل، المميز) ويجيب الطلاب فرديًا.",
                "يقدم المعلم التغذية الراجعة المناسبة.", "مناقشة الطلبة في أهداف التعلم المنشودة في الحصة."),
        blocks=tuple(blocks),
        closing=("استراتيجية الدقيقة الواحدة: يوجه المعلم الطلاب للإجابة عن سؤال المميز في العرض.",
                 "يعرض الطلاب الحل. يقدم المعلم تغذية راجعة مناسبة."),
        homework="على منصة تعليم قطر: تقييم المراجعة (حل أسئلة التقييم الذاتي)."))


def build_deck(req: ReviewRequest, template: Path, path: Path) -> None:
    examples = []
    for skill in review_bank.SKILLS:
        item = next(i for i in review_bank.by_skill(skill) if i.choices)
        examples.append(deck_pptx.Example(skill, ltr(item.text), ltr(f"الحل: {item.work} ← الإجابة: {item.choices[0]}")))
    closing = next(i for i in review_bank.by_skill(review_bank.S6) if i.choices)
    deck_pptx.build(template, path, deck_pptx.DeckContent(
        title=req.title, goals=("أحل المعادلات التربيعية", "أحل المتباينات والدائرة"),
        term="المعادلة التربيعية | Quadratic equation",
        objectives=("أراجع حل المعادلات التربيعية.", "أحل المتباينات والأنظمة والدائرة."),
        examples=tuple(examples), activity="أمامك 10 دقائق لحل ورقة العمل (الأسئلة المرقمة)",
        fast="للطلاب سريعي الإنجاز: أكمل جميع بنود ورقة العمل.",
        closing_question=ltr(closing.text), closing_answer=ltr(f"الإجابة: {closing.choices[0]}")))


def _objectives_html() -> str:
    items = "".join(f"<li>أراجع {s}.</li>" for s in review_bank.SKILLS)
    return f"<h3>أهداف الدرس</h3><ul>{items}</ul>"


def _steps_html() -> str:
    return ("<h3>سير الحصة</h3><ol><li>تهيئة: سؤالان سريعان.</li><li>عرض المراجعة ومناقشة بنود صح/خطأ.</li>"
            "<li>ورقة العمل في مجموعات.</li><li>التقييم الذاتي التصحيح.</li></ol>")


def design(req: ReviewRequest, out: Path) -> Path:
    """يكتب المجلد ويعيد مسار lesson.json. يُعاد استدعاؤه بأمان: يستبدل ملفاته المولّدة وحدها."""
    out.mkdir(parents=True, exist_ok=True)
    deck_t, plan_t = find_templates(req)
    build_deck(req, deck_t, out / "deck.pptx")
    build_worksheet(req, out / "worksheet.docx")
    build_plan(req, plan_t, out / "plan.docx")
    quiz = assessment.to_text(review_bank.review_quiz())
    spec = {
        "class": req.lms_id, "academic_year": req.academic_year, "title": req.title,
        "description": f"مراجعة شاملة لمهارات {req.unit_title} بمثال محلول لكل مهارة وورقة عمل وتقييم ذاتي التصحيح.",
        "date": req.day.isoformat(), "period": req.period, "grade": req.grade, "term": req.term,
        "before_title": req.before_title, "outcome_prefixes": list(req.outcome_prefixes),
        "show": req.show, "points": req.points,
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
