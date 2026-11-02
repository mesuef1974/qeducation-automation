"""كيانات نقية لطبقة المنصة - بلا Django."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ParsedLesson:
    lms_lesson_id: int
    position: int
    title: str
    description: str
    date: date | None
    period: int | None
    hidden: bool = False         # «شخصى»: مخفي افتراضيًا عن الطلاب
    awards_points: bool = False  # «يمنح النقاط»: له إجراء إنجاز يمنح نقاطًا


@dataclass(frozen=True)
class ParsedTile:
    """ما تعرضه بطاقة الدرس في قائمة المعلم عن جودته."""
    lms_lesson_id: int
    image_default: bool   # صورة من مكتبة المنصة العامة لا من المحتوى
    sections: int
    has_outcomes: bool    # شارة «نتاجات التعلم»


@dataclass(frozen=True)
class ParsedSection:
    section_id: int
    title: str
    kind: str  # من SECTION_KINDS، أو الأيقونة الخام إن لم تُعرف


@dataclass(frozen=True)
class ParsedAssessment:
    lms_assignment_id: int
    title: str
    lms_lesson_id: int | None
    given: bool


@dataclass(frozen=True)
class ParsedSlot:
    weekday: int  # Python weekday()
    period: int


@dataclass(frozen=True)
class Target:
    """بند في الخطة يمكن أن يُطابَق به درس على المنصة."""
    code: str          # "2.1" أو "مراجعة واختبار وحدة#1"
    title: str
    order: int         # ترتيب الظهور في التوزيع
    weeks: frozenset[int]
    plan_periods: int
    is_lesson: bool


@dataclass(frozen=True)
class Match:
    code: str | None
    score: float


@dataclass(frozen=True)
class Slot:
    date: date
    period: int
    week_no: int

    @property
    def key(self) -> tuple[date, int]:
        return (self.date, self.period)


@dataclass
class ProposalDraft:
    lesson_id: int
    slot: Slot
    flags: list[str] = field(default_factory=list)
