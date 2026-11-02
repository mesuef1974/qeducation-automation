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
