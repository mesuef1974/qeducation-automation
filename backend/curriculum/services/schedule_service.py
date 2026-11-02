from datetime import date

from curriculum.domain.entities import EntryItem, EventItem, PlanProgress, WeekSnapshot
from curriculum.repositories.plan_repo import PlanRepository


class PlanNotFound(LookupError):
    pass


class ScheduleService:
    """منطق التوزيع: أسبوع اليوم، أسبوع برقمه، ونسبة التقدم وفق الخطة."""

    def __init__(self, repo: PlanRepository | None = None):
        self.repo = repo or PlanRepository()

    def _plan(self, grade_level: int):
        plan = self.repo.get_by_grade(grade_level)
        if plan is None:
            raise PlanNotFound(f"no plan for grade {grade_level}")
        return plan

    def week_for_date(self, grade_level: int, d: date) -> WeekSnapshot | None:
        """الأسبوع الذي يقع فيه التاريخ؛ في نهاية الأسبوع يُعاد الأسبوع القادم. None بعد نهاية الفصل."""
        plan = self._plan(grade_level)
        week = self.repo.week_on_or_after(plan, d)
        if week is None:
            return None
        status = "current" if week.start_date <= d <= week.end_date else "upcoming"
        return self._snapshot(plan, week, status)

    def week_by_no(self, grade_level: int, week_no: int) -> WeekSnapshot | None:
        plan = self._plan(grade_level)
        week = self.repo.week_by_no(plan, week_no)
        return self._snapshot(plan, week, "requested") if week else None

    def progress(self, grade_level: int, d: date) -> PlanProgress:
        """ما يُفترض إنجازه حتى نهاية آخر أسبوع منتهٍ قبل التاريخ."""
        plan = self._plan(grade_level)
        lessons = self.repo.scheduled_lessons_with_last_week_end(plan)
        return PlanProgress(
            grade_level=grade_level,
            as_of=d,
            planned_periods_done=self.repo.periods_until(plan, d),
            total_periods=self.repo.total_periods(plan),
            lessons_done=[f"{c} {t}" for c, t, end in lessons if end < d],
            lessons_remaining=[f"{c} {t}" for c, t, end in lessons if end >= d],
        )

    def _snapshot(self, plan, week, status: str) -> WeekSnapshot:
        entries = self.repo.entries(week)
        return WeekSnapshot(
            grade_level=plan.grade_level,
            platform_class=plan.platform_class,
            week_no=week.week_no,
            start_date=week.start_date,
            end_date=week.end_date,
            week_type=week.week_type,
            status=status,
            total_periods=sum(e.periods for e in entries),
            entries=[EntryItem(
                seq=e.seq, activity_type=e.activity_type,
                lesson_code=e.lesson.code if e.lesson else None,
                title=e.title, periods=e.periods,
                unit_no=e.unit.unit_no if e.unit else None,
            ) for e in entries],
            events=[EventItem(ev.event_type, ev.title, ev.start_date, ev.end_date)
                    for ev in self.repo.events_overlapping(plan, week.start_date, week.end_date)],
        )
