"""
مواصفة درس جديد كاملة (ملف JSON يكتبه المعلم أو يصوغه Claude ويعتمده المعلم قبل الإنشاء):
العنوان والوصف والتاريخ والحصة والكلمات والنتاجات وأقسام الصفحات وعروض الأقسام وتقييم ذاتي التصحيح وملفات الملاحظات.
التحقق هنا نقي (بلا شبكة ولا ORM): يرفض الناقص برسالة عربية واضحة قبل أن تُكتب أي كلمة على المنصة.
"""
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from neo.domain import assessment, keywords

MAX_TITLE = 120
ROLE_PREFIXES = ("التحضير", "ورقة عمل", "عرض الدرس")


class SpecError(ValueError):
    """مواصفة غير صالحة؛ تُصلح ثم يُعاد التشغيل."""


@dataclass(frozen=True)
class PageSection:
    name: str
    html: str


@dataclass(frozen=True)
class FileSection:
    title: str
    path: Path


@dataclass(frozen=True)
class NoteFile:
    label: str   # «التحضير - …» «ورقة عمل - …» «عرض الدرس - …»
    path: Path


@dataclass(frozen=True)
class LessonSpec:
    lms_id: int
    academic_year: str
    title: str
    description: str
    day: date
    period: int
    grade: str
    term: str
    before_title: str = ""            # يُرتَّب قبل هذا الدرس؛ فارغ = في النهاية
    tags: tuple[str, ...] = ()
    outcome_codes: tuple[str, ...] = ()
    outcome_prefixes: tuple[str, ...] = ()  # كل نتاجات الصف التي يبدأ رمزها بأحدها (مثل «10.2.» لوحدة)
    show: bool = False                      # يُظهر الدرس بعد اكتمال بنائه
    pages: tuple[PageSection, ...] = ()
    decks: tuple[FileSection, ...] = ()
    quiz_name: str = ""
    quiz: tuple[assessment.Question, ...] = ()
    notes: tuple[NoteFile, ...] = ()
    points: dict = field(default_factory=dict)  # {"points": 5, "game": "...", "notification": "Popup"} اختياري


def _need(d: dict, key: str, what: str):
    v = d.get(key)
    if v in (None, "", []):
        raise SpecError(f"المواصفة بلا {what} («{key}»)")
    return v


def _file(base: Path, rel: str, what: str) -> Path:
    p = (base / rel).resolve()
    if not p.is_file():
        raise SpecError(f"ملف {what} غير موجود: {rel}")
    return p


def load(path: Path) -> LessonSpec:
    base = path.parent
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"تعذّرت قراءة المواصفة: {exc}") from exc
    return parse(d, base)


def parse(d: dict, base: Path) -> LessonSpec:
    title = " ".join(str(_need(d, "title", "عنوان")).split())
    if len(title) > MAX_TITLE:
        raise SpecError(f"العنوان أطول من {MAX_TITLE} حرفًا")
    try:
        day = date.fromisoformat(str(_need(d, "date", "تاريخ")))
    except ValueError as exc:
        raise SpecError("التاريخ بصيغة YYYY-MM-DD") from exc
    period = int(_need(d, "period", "حصة"))
    if not 1 <= period <= 7:
        raise SpecError("الحصة من 1 إلى 7")
    tags = tuple(keywords.clean(t) for t in d.get("tags", []))
    if len(tags) > keywords.MAX_TAGS or not all(tags):
        raise SpecError(f"الكلمات الدلالية: حتى {keywords.MAX_TAGS} وبلا فارغ")
    pages = tuple(PageSection(" ".join(str(_need(s, "name", "اسم قسم")).split()), str(_need(s, "html", "محتوى قسم")))
                  for s in d.get("pages", []))
    decks = tuple(FileSection(" ".join(str(_need(s, "title", "عنوان عرض")).split()), _file(base, _need(s, "file", "ملف"), "العرض"))
                  for s in d.get("decks", []))
    notes = tuple(NoteFile(" ".join(str(_need(n, "label", "عنوان ملف")).split()), _file(base, _need(n, "file", "ملف"), "الملاحظات"))
                  for n in d.get("notes", []))
    for n in notes:
        if not n.label.startswith(ROLE_PREFIXES):
            raise SpecError(f"عنوان ملف الملاحظات يبدأ بدوره ({'، '.join(ROLE_PREFIXES)}): «{n.label}»")
    quiz = ()
    if d.get("quiz"):
        try:
            quiz = tuple(assessment.parse_text(str(d["quiz"])))
        except ValueError as exc:
            raise SpecError(f"التقييم: {exc}") from exc
    pts = d.get("points") or {}
    if pts and not (isinstance(pts.get("points"), int) and pts["points"] > 0 and pts.get("game") and pts.get("notification")):
        raise SpecError("النقاط: points (عدد موجب) وgame وnotification مطلوبة")
    names = [p.name for p in pages] + [s.title for s in decks]
    if len(set(names)) != len(names):
        raise SpecError("أسماء الأقسام مكررة")
    return LessonSpec(
        lms_id=int(_need(d, "class", "رقم الصف على المنصة")), academic_year=str(_need(d, "academic_year", "عام دراسي")),
        title=title, description=str(_need(d, "description", "وصف")).strip(), day=day, period=period,
        grade=str(_need(d, "grade", "مستوى دراسي")), term=str(_need(d, "term", "فصل دراسي")),
        before_title=" ".join(str(d.get("before_title", "")).split()), tags=tags,
        outcome_codes=tuple(str(c) for c in d.get("outcome_codes", [])),
        outcome_prefixes=tuple(str(c) for c in d.get("outcome_prefixes", [])), show=bool(d.get("show", False)), pages=pages, decks=decks,
        quiz_name=str(d.get("quiz_name") or assessment.QUIZ_NAME), quiz=quiz, notes=notes,
        points=dict(d.get("points", {})),
    )
