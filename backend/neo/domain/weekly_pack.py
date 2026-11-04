"""
حزمة التحضير الأسبوعية: منطق خالص بلا Django ولا منصة.

مصدر دروس الأسبوع هو الخطة لا تواريخ المنصة: عدد الدروس = مجموع حصص بنود الأسبوع، وأجزاء كل موضوع
تبدأ بعد ما استهلكته الأسابيع السابقة منه. يُربط كل جزء بدرس المنصة بالموضوع ورقم الجزء، ثم تُوزَّع
الدروس بالترتيب على حصص الأسبوع في جدول الصف. أي اختلاف بين العددين يوقف الحزمة ويطلب قرار المعلم.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from neo.domain.bidi import LRM, latin_item
from neo.domain.question_bank import part_of, topic_of
from neo.domain.types import FileLink, Slot
from neo.services.matching import normalize, strip_part
from neo.services.scheduling import WeekSpan, build_slots

DAY_NAMES = {6: "الأحد", 0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس"}
MESSAGE_HEADER = ("الصف", "الموضوع", "صفحات الكتاب", "الواجبات", "الاختبارات", "التوقيع")
NO_TESTS = "لا يوجد"


class PackError(ValueError):
    """لا تُبنى الحزمة إلا بقرار من المعلم (عدد الدروس لا يساوي عدد الحصص، أو جزء بلا درس على المنصة)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class PlanEntry:
    """بند في التوزيع الأسبوعي للخطة. code: رمز الدرس (3.1)، أو «النوع#الوحدة» لنشاط غير درسي."""
    week_no: int
    seq: int
    code: str
    title: str
    periods: int
    is_lesson: bool = True


@dataclass(frozen=True)
class LessonRef:
    """درس على المنصة كما في قاعدة البيانات (code = المطابقة الفعلية)."""
    lms_lesson_id: int
    position: int
    title: str
    code: str = ""
    date: date | None = None
    period: int | None = None


@dataclass(frozen=True)
class PackLesson:
    lms_lesson_id: int
    position: int
    title: str          # عنوان الدرس على المنصة
    plan_title: str     # عنوان الموضوع في الخطة
    code: str
    part: int
    date: date
    period: int
    platform_date: date | None = None
    platform_period: int | None = None

    @property
    def day_name(self) -> str:
        return DAY_NAMES.get(self.date.weekday(), "")

    @property
    def date_text(self) -> str:
        return date_text(self.date)

    @property
    def folder(self) -> str:
        return safe_name(f"{self.position} - {self.plan_title} {self.part}")

    @property
    def platform_differs(self) -> bool:
        return (self.platform_date, self.platform_period) != (self.date, self.period)


def date_text(d: date) -> str:
    """8/11/2026: اليوم/الشهر/السنة بلا أصفار بادئة، كما في نماذج التحضير."""
    return f"{d.day}/{d.month}/{d.year}"


# ------------------------------------------------------------- الموضوع ورقم الجزء

_PART_TAIL = re.compile(r"(?:\(\s*)?(?:ج\s*)?(\d+)\s*\)?\s*$")


def lesson_part(title: str) -> int:
    """«القيم القصوى  للدوال 3» → 3؛ «رسم منحنيات الدوال ج2» → 2؛ «الاتصال(2)» → 2؛ بلا رقم → 1."""
    m = _PART_TAIL.search(title.strip())
    return int(m.group(1)) if m else part_of(title)


def topic_key(title: str) -> str:
    """مفتاح مقارنة الموضوع: بلا رقم الجزء، وبتوحيد الهمزة والتاء المربوطة، وبلا مسافات
    («الدوال المتزايدة و المتناقصة 2» = «الدوال المتزايدة والمتناقصة»)."""
    return normalize(topic_of(strip_part(title))).replace(" ", "")


# ------------------------------------------------------------- دروس الأسبوع

def week_parts(entries: list[PlanEntry], week_no: int) -> list[tuple[PlanEntry, int]]:
    """أجزاء الأسبوع بترتيب بنوده: لكل بند حصصه مرقمة بعد ما استهلكته الأسابيع السابقة من موضوعه."""
    used: dict[str, int] = defaultdict(int)
    for e in entries:
        if e.week_no < week_no:
            used[e.code] += e.periods
    out = []
    for e in sorted((e for e in entries if e.week_no == week_no), key=lambda e: e.seq):
        out += [(e, used[e.code] + i) for i in range(1, e.periods + 1)]
        used[e.code] += e.periods
    return out


def _find(lessons: list[LessonRef], entry: PlanEntry, part: int) -> LessonRef | None:
    key = topic_key(entry.title)
    same = [pl for pl in lessons if (pl.code and pl.code == entry.code) or topic_key(pl.title) == key]
    by_title = [pl for pl in same if lesson_part(pl.title) == part]
    if len(by_title) == 1:
        return by_title[0]
    ordered = sorted(same, key=lambda pl: pl.position)  # عنوان بلا رقم أو مكرر: الترتيب على المنصة
    return ordered[part - 1] if not by_title and len(ordered) >= part else None


def week_slots(week: WeekSpan, timetable: list[tuple[int, int]], days_off: set[date]) -> list[Slot]:
    return [s for s in build_slots([week], timetable) if s.date not in days_off]


def select_week(entries: list[PlanEntry], lessons: list[LessonRef], week: WeekSpan,
                timetable: list[tuple[int, int]], days_off: set[date] = frozenset()) -> list[PackLesson]:
    """دروس الأسبوع موزعة على حصصه بالترتيب. PackError إن لم تكتمل المطابقة أو اختلف العددان."""
    if not week.teaching:
        raise PackError(f"الأسبوع {week.week_no} إجازة في الخطة.")
    parts = week_parts(entries, week.week_no)
    slots = week_slots(week, timetable, days_off)
    matched, missing = [], []
    for entry, part in parts:
        pl = _find(lessons, entry, part)
        if pl is None:
            missing.append(f"{entry.title} {part}")
        else:
            matched.append((entry, part, pl))
    details = {"plan_periods": len(parts), "slots": len(slots), "missing": missing,
               "parts": [f"{e.title} {p}" for e, p in parts]}
    if missing:
        raise PackError(f"أجزاء في الخطة بلا درس على المنصة: {'، '.join(missing)}. "
                        "أضف الدرس على المنصة أو عدّل مطابقته، ثم أعد التشغيل.", details)
    if len({pl.lms_lesson_id for _, _, pl in matched}) != len(matched):
        raise PackError("درس واحد على المنصة طابق أكثر من جزء في الخطة؛ راجع المطابقة.", details)
    if len(matched) != len(slots):
        raise PackError(f"عدد دروس الأسبوع في الخطة ({len(matched)}) لا يساوي حصصه في الجدول ({len(slots)}). "
                        "قرّر توزيعها ثم أعد التشغيل.", details)
    return [PackLesson(pl.lms_lesson_id, pl.position, pl.title, e.title, e.code, part, s.date, s.period,
                       pl.date, pl.period)
            for (e, part, pl), s in zip(matched, slots)]


# ------------------------------------------------------------- أسماء الملفات

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_KNOWN_EXT = re.compile(r"\.(docx|pptx|pdf|doc|ppt)$", re.I)
WORKSHEET_STEMS = ("wrq_ml", "mrj")
SECTIONS_DIR = "عروض الأقسام"


def safe_name(text: str, limit: int = 150, stem: bool = False) -> str:
    """اسم صالح في ويندوز: كل محرف ممنوع يصير مسافة، بلا نقطة أو مسافة في الآخر.
    stem: جذر اسم ملف يليه امتداد، فتبقى نقطته الأخيرة كما كتبها المعلم («الأولى.» ← «الأولى..pptx»)."""
    name = _FORBIDDEN.sub(" ", text).strip()[:limit]
    return (name.rstrip(" ") if stem else name.rstrip(" .")) or "ملف"


def link_title(link: FileLink) -> str:
    return _KNOWN_EXT.sub("", link.name.strip()) or link.stem


def note_role(link: FileLink) -> str:
    """ملاحظات المعلم: ورقة العمل اسمها المرمّز يبدأ بـ wrq_ml أو mrj، وبقية الوورد تحضير، والعرض عرض الدرس."""
    if link.ext == "pptx":
        return "presentation"
    if link.ext == "docx":
        return "worksheet" if link.stem.lower().startswith(WORKSHEET_STEMS) else "prep"
    return "other"


ROLE_PREFIX = {"prep": "التحضير", "worksheet": "ورقة عمل", "presentation": "عرض الدرس"}


def note_file_name(link: FileLink) -> str:
    """ملف من الملاحظات باسم الرابط كما يراه المعلم، مسبوقًا بدوره: «التحضير - …» «عرض الدرس - …» «ورقة عمل - …»."""
    return safe_name(f"{ROLE_PREFIX[note_role(link)]} - {link_title(link)}", stem=True) + f".{link.ext}"


def section_file_name(index: int, section_title: str, link: FileLink) -> str:
    """عرض قسم باسم القسم في الدرس (لا اسم الرابط)، مرقّمًا بترتيبه: «1 - العرض التقديمي- أجد …»."""
    return safe_name(f"{index} - {section_title.strip() or link_title(link)}", stem=True) + f".{link.ext}"


def week_folder(pattern: str, week_no: int, section: str) -> str:
    return safe_name(pattern.format(week=week_no, section=section.replace("/", "-")))


def class_section(class_name: str) -> str:
    """«الرياضيات 12/2» → «12/2»."""
    m = re.search(r"\d+\s*/\s*\d+", class_name)
    return m.group(0).replace(" ", "") if m else class_name


# ------------------------------------------------------------- صف الرسالة الأسبوعية

@dataclass(frozen=True)
class Book:
    """كتاب الطالب: صفحات كل درس كما في فهرسه (صفحة الكتاب = صفحة PDF − pdf_offset)، تُدخل بعد التحقق مرة واحدة.
    part_end: آخر صفحة يبلغها جزء بعينه حين لا يغطي الأسبوع الدرس كله."""
    title: str
    pdf_offset: int
    lessons: dict[str, tuple[int, int]]
    part_end: dict[tuple[str, int], int] = field(default_factory=dict)


# (المستوى، الفصل، المسار) ← الكتاب
BOOKS: dict[tuple[int, int, str], Book] = {
    (12, 1, "علمي"): Book("كتاب الطالب - الرياضيات 12 علمي وتكنولوجي - الفصل الأول", 8,
                          {"3.1": (144, 153), "3.2": (154, 168)}, {("3.2", 3): 163}),
}


def book_for(grade: int, term: int, tracks: str) -> Book | None:
    return next((b for (g, t, track), b in BOOKS.items() if g == grade and t == term and track in tracks), None)


def week_pages(book: Book | None, lessons: list[PackLesson]) -> tuple[str, list[str]]:
    """(«144–163»، الدروس التي لا صفحات لها في الجدول). النطاق بعلامة LRM حتى لا يظهر «163–144» في السطر العربي."""
    if book is None:
        return "", sorted({pl.code for pl in lessons})
    known = [pl for pl in lessons if pl.code in book.lessons]
    unknown = sorted({pl.code for pl in lessons if pl.code not in book.lessons})
    if not known:
        return "", unknown
    first = min(book.lessons[pl.code][0] for pl in known)
    last_lesson = known[-1]
    last = book.part_end.get((last_lesson.code, last_lesson.part), book.lessons[last_lesson.code][1])
    return f"{LRM}{first}–{last}", unknown


def topics_text(lessons: list[PackLesson]) -> str:
    """«الدوال المتزايدة والمتناقصة (2–4)، القيم القصوى للدوال (1–3)»، والنطاق بعلامة LRM فلا يُقلب."""
    groups: dict[str, list[int]] = {}
    for pl in lessons:
        groups.setdefault(pl.plan_title, []).append(pl.part)
    out = []
    for title, parts in groups.items():
        lo, hi = min(parts), max(parts)
        out.append(f"{title} ({lo})" if lo == hi else f"{title} ({LRM}{lo}–{hi})")
    return "، ".join(out)


# «تدريب 20a صفحة 151 كتاب الطالب»، «تمرين 6 ص 151»، «التمرين رقم 11 ص 151»؛ لا ما في دليل التقويم
_EXERCISE = re.compile(r"(?:ال)?(?:تدريب|تمرين)\s*(?:رقم\s*)?(\d+[a-zA-Z]?)\s*(?:صفحة|ص)\s*\.?\s*(\d+)(?P<tail>[^\n]{0,25})")
# «الواجب صفحة 151 رقم 19و20»
_HOMEWORK = re.compile(r"الواجب\s*:?\s*(?:صفحة|ص)\s*\.?\s*(\d+)\s*(?:رقم|تدريب|تمارين)?\s*([0-9a-zA-Z\sو،,\-]+)")


def _numbers(raw: str) -> list[str]:
    return re.findall(r"\d+[a-zA-Z]?", raw)


def book_exercises(texts: list[str]) -> dict[int, list[str]]:
    """تدريبات كتاب الطالب المذكورة في نص التحضير: الصفحة ← الأرقام بترتيب ظهورها بلا تكرار."""
    found: dict[int, list[str]] = {}
    for text in texts:
        for m in _EXERCISE.finditer(text):
            if "دليل" in m.group("tail"):
                continue
            found.setdefault(int(m.group(2)), []).append(m.group(1))
        for m in _HOMEWORK.finditer(text):
            found.setdefault(int(m.group(1)), []).extend(_numbers(m.group(2)))
    return {page: list(dict.fromkeys(nums)) for page, nums in sorted(found.items())}


def _ex_key(n: str) -> tuple[int, str]:
    m = re.match(r"(\d+)(.*)", n)
    return (int(m.group(1)), m.group(2)) if m else (0, n)


def homework_text(exercises: dict[int, list[str]], final_assessments: int) -> str:
    # «17a» تُتبع بعلامة RLM، وإلا انقلب ترتيب ما بعدها من أرقام في السطر العربي
    parts = [f"ص{page}: {'، '.join(latin_item(n) for n in sorted(nums, key=_ex_key))}"
             for page, nums in sorted(exercises.items())]
    text = ("تدريبات كتاب الطالب " + "؛ ".join(parts)) if parts else ""
    if final_assessments:
        tail = f"التقييم الختامي على المنصة ({final_assessments})"
        text = f"{text}، و{tail}" if text else tail
    return text


def tests_text(events: list[tuple[str, date, date]]) -> str:
    if not events:
        return NO_TESTS
    return "، ".join(f"{title} ({date_text(s)}{'' if s == e else ' – ' + date_text(e)})" for title, s, e in events)


def message_row(section: str, lessons: list[PackLesson], pages: str, homework: str, tests: str) -> list[str]:
    return [section, topics_text(lessons), pages, homework, tests, ""]


def message_tsv(row: list[str]) -> str:
    clean = [c.replace("\t", " ").replace("\n", " ") for c in row]
    return "\t".join(MESSAGE_HEADER) + "\n" + "\t".join(clean) + "\n"
