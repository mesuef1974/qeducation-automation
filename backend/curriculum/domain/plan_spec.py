"""
ملف الخطة الموحّد: وصف نقي لخطة فصلية واحدة (أي مادة، أي فصل) مع قواعد تحققها.
لا يعتمد على Django ولا على صيغة الملف؛ القارئ والكاتب في curriculum/infrastructure/plan_workbook.py.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

TEACHING, BREAK = "تدريس", "إجازة"
LESSON = "درس"


@dataclass(frozen=True)
class SourceInfo:
    file_name: str
    page_count: int
    form_code: str = "ES-ESM-P3-F1"
    issue_no: int = 1
    issue_date: date = date(2024, 5, 30)
    classification: str = "داخلي"
    department: str = ""


@dataclass(frozen=True)
class WeekSpec:
    week_no: int
    start_date: date
    end_date: date
    week_type: str = TEACHING
    note: str = ""
    expected_periods: int | None = None  # مجموع الأسبوع كما في الأصل - للتحقق


@dataclass(frozen=True)
class UnitSpec:
    unit_no: int
    title: str
    domain: str = ""


@dataclass(frozen=True)
class EntrySpec:
    week_no: int
    unit_no: int | None
    activity_type: str
    lesson_code: str | None
    title: str
    periods: int


@dataclass(frozen=True)
class ExtraLessonSpec:
    """درس وارد في الخطة خارج التوزيع الأسبوعي (إثرائي فقط)."""

    unit_no: int
    code: str
    title: str


@dataclass(frozen=True)
class OutcomeBlockSpec:
    unit_no: int
    week_from: int
    week_to: int
    competencies: tuple[str, ...]
    values: tuple[str, ...]
    outcomes: tuple[str, ...]


@dataclass(frozen=True)
class EnrichmentSpec:
    lesson_code: str
    detail: str = ""


@dataclass(frozen=True)
class EventSpec:
    event_type: str
    title: str
    start_date: date
    end_date: date
    note: str = ""


@dataclass(frozen=True)
class PlanSpec:
    subject: str
    academic_year: str
    term_no: int
    grade_level: int
    shift: str
    source: SourceInfo
    tracks: str = ""
    platform_class: str = ""
    weeks: tuple[WeekSpec, ...] = ()
    units: tuple[UnitSpec, ...] = ()
    entries: tuple[EntrySpec, ...] = ()
    extra_lessons: tuple[ExtraLessonSpec, ...] = ()
    outcome_blocks: tuple[OutcomeBlockSpec, ...] = ()
    enrichment: tuple[EnrichmentSpec, ...] = ()
    events: tuple[EventSpec, ...] = ()
    guidelines: tuple[tuple[str, str], ...] = ()      # (العنوان، النص)
    methodology: tuple[tuple[str, str], ...] = ()     # (الجزئية، الإجراء)

    def __str__(self):
        tracks = f" ({self.tracks})" if self.tracks else ""
        return f"{self.subject} - المستوى {self.grade_level}{tracks} - {self.academic_year} ف{self.term_no}"

    # ------------------------------------------------------------- مشتقات

    def lessons(self) -> list[tuple[int, str, str, bool, int]]:
        """[(الوحدة، الرمز، العنوان، في التوزيع، مجموع الحصص)] بترتيب أول ظهور ثم الدروس الإضافية."""
        periods, first = Counter(), {}
        for e in self.entries:
            if e.lesson_code:
                periods[e.lesson_code] += e.periods
                first.setdefault(e.lesson_code, (e.unit_no, e.title))
        out = [(u, c, t, True, periods[c]) for c, (u, t) in first.items()]
        return out + [(x.unit_no, x.code, x.title, False, 0) for x in self.extra_lessons]

    def week_totals(self) -> dict[int, int]:
        totals = {w.week_no: 0 for w in self.weeks}
        for e in self.entries:
            totals[e.week_no] = totals.get(e.week_no, 0) + e.periods
        return totals

    # ------------------------------------------------------------- تحقق

    def validate(self) -> list[str]:
        """قائمة أخطاء بالعربية (فارغة = الخطة سليمة)."""
        errs: list[str] = []
        if not (self.subject and self.academic_year and self.shift):
            errs.append("بيانات الخطة: المادة والعام الأكاديمي والفترة مطلوبة")
        if len(self.academic_year) != 9 or self.academic_year[4] != "-":
            errs.append(f"بيانات الخطة: العام الأكاديمي بصيغة 2026-2027 (وُجد {self.academic_year!r})")
        if self.term_no not in (1, 2, 3):
            errs.append(f"بيانات الخطة: الفصل 1 أو 2 أو 3 (وُجد {self.term_no})")

        weeks = {w.week_no: w for w in self.weeks}
        if not weeks:
            errs.append("الأسابيع: لا توجد أسابيع")
        for no, n in Counter(w.week_no for w in self.weeks).items():
            if n > 1:
                errs.append(f"الأسابيع: الأسبوع {no} مكرر")
        for w in self.weeks:
            if w.end_date < w.start_date:
                errs.append(f"الأسابيع: الأسبوع {w.week_no} ينتهي قبل أن يبدأ")
            if w.start_date.weekday() != 6:
                errs.append(f"الأسابيع: الأسبوع {w.week_no} يجب أن يبدأ يوم الأحد ({w.start_date})")
            if w.week_type not in (TEACHING, BREAK):
                errs.append(f"الأسابيع: نوع الأسبوع {w.week_no} «{TEACHING}» أو «{BREAK}»")

        units = {u.unit_no for u in self.units}
        for no, n in Counter(u.unit_no for u in self.units).items():
            if n > 1:
                errs.append(f"الوحدات: الوحدة {no} مكررة")

        lesson_unit: dict[str, int | None] = {}
        for i, e in enumerate(self.entries, 1):
            where = f"التوزيع، البند {i} ({e.title})"
            if e.week_no not in weeks:
                errs.append(f"{where}: الأسبوع {e.week_no} غير معرّف")
            elif weeks[e.week_no].week_type == BREAK:
                errs.append(f"{where}: الأسبوع {e.week_no} إجازة")
            if e.unit_no is not None and e.unit_no not in units:
                errs.append(f"{where}: الوحدة {e.unit_no} غير معرّفة")
            if e.periods <= 0:
                errs.append(f"{where}: عدد الحصص يجب أن يكون موجبًا")
            if e.activity_type == LESSON and not e.lesson_code:
                errs.append(f"{where}: بند من نوع «درس» بلا رمز درس")
            if e.lesson_code:
                if e.unit_no is None:
                    errs.append(f"{where}: الدرس {e.lesson_code} بلا وحدة")
                prev = lesson_unit.setdefault(e.lesson_code, e.unit_no)
                if prev != e.unit_no:
                    errs.append(f"{where}: الدرس {e.lesson_code} في وحدتين مختلفتين")

        codes = set(lesson_unit)
        for x in self.extra_lessons:
            if x.code in codes:
                errs.append(f"دروس خارج التوزيع: {x.code} موجود في التوزيع")
            if x.unit_no not in units:
                errs.append(f"دروس خارج التوزيع: الوحدة {x.unit_no} غير معرّفة ({x.code})")
            codes.add(x.code)

        for w, actual in self.week_totals().items():
            exp = weeks[w].expected_periods if w in weeks else None
            if exp is not None and exp != actual:
                errs.append(f"الأسابيع: مجموع الأسبوع {w} = {actual} والأصل {exp}")

        for b in self.outcome_blocks:
            where = f"المكتسبات، الوحدة {b.unit_no} الأسابيع {b.week_from}-{b.week_to}"
            if b.unit_no not in units:
                errs.append(f"{where}: الوحدة غير معرّفة")
            if b.week_from > b.week_to:
                errs.append(f"{where}: مدى الأسابيع معكوس")
            if not b.outcomes:
                errs.append(f"{where}: بلا مكتسبات")

        for x in self.enrichment:
            if x.lesson_code not in codes:
                errs.append(f"الإثراء: الدرس {x.lesson_code} غير موجود في الخطة")

        for ev in self.events:
            if ev.end_date < ev.start_date:
                errs.append(f"التقويم: «{ev.title}» ينتهي قبل أن يبدأ")
        return errs


class PlanFileError(ValueError):
    def __init__(self, source: str, errors: list[str]):
        self.source, self.errors = source, errors
        super().__init__(f"{source}:\n" + "\n".join(f"  - {e}" for e in errors))


def group_blocks(rows: list[tuple[int, int, int, int, tuple, tuple, str]]) -> tuple[OutcomeBlockSpec, ...]:
    """صفوف المكتسبات (الكتلة، الوحدة، من، إلى، الكفايات، القيم، النص) ← كتل؛ بيانات الكتلة من أول صف."""
    head, texts = {}, defaultdict(list)
    for block, unit, w_from, w_to, comps, vals, text in rows:
        head.setdefault(block, (unit, w_from, w_to, comps, vals))
        texts[block].append(text)
    return tuple(OutcomeBlockSpec(*head[b][:3], head[b][3], head[b][4], tuple(texts[b])) for b in head)
