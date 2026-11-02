"""كيانات نقية بلا اعتماد على Django - تُعاد من الخدمات وتُسلسل في الـ API."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class EntryItem:
    seq: int
    activity_type: str
    lesson_code: str | None
    title: str
    periods: int
    unit_no: int | None


@dataclass(frozen=True)
class EventItem:
    event_type: str
    title: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class WeekSnapshot:
    plan_id: int
    grade_level: int
    platform_class: str
    week_no: int
    start_date: date
    end_date: date
    week_type: str
    status: str  # current | upcoming
    total_periods: int
    entries: list[EntryItem] = field(default_factory=list)
    events: list[EventItem] = field(default_factory=list)


@dataclass(frozen=True)
class PlanProgress:
    plan_id: int
    grade_level: int
    as_of: date
    planned_periods_done: int
    total_periods: int
    lessons_done: list[str]
    lessons_remaining: list[str]

    @property
    def percent(self) -> float:
        return round(100 * self.planned_periods_done / self.total_periods, 1) if self.total_periods else 0.0
