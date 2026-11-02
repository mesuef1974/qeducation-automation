from datetime import date

from django.db.models import Max, Sum

from curriculum.models import CalendarEvent, Lesson, Plan, ScheduleEntry, Week


class PlanRepository:
    def get(self, plan_id: int) -> Plan | None:
        return Plan.objects.filter(pk=plan_id).first()

    def week_on_or_after(self, plan: Plan, d: date) -> Week | None:
        return Week.objects.filter(plan=plan, end_date__gte=d).order_by("start_date").first()

    def week_by_no(self, plan: Plan, week_no: int) -> Week | None:
        return Week.objects.filter(plan=plan, week_no=week_no).first()

    def entries(self, week: Week) -> list[ScheduleEntry]:
        return list(ScheduleEntry.objects.filter(week=week).select_related("lesson", "unit").order_by("seq"))

    def events_overlapping(self, plan: Plan, start: date, end: date) -> list[CalendarEvent]:
        return list(CalendarEvent.objects.filter(plan=plan, start_date__lte=end, end_date__gte=start))

    def periods_until(self, plan: Plan, d: date) -> int:
        return ScheduleEntry.objects.filter(plan=plan, week__end_date__lt=d).aggregate(s=Sum("periods"))["s"] or 0

    def total_periods(self, plan: Plan) -> int:
        return ScheduleEntry.objects.filter(plan=plan).aggregate(s=Sum("periods"))["s"] or 0

    def scheduled_lessons_with_last_week_end(self, plan: Plan):
        """[(code, title, آخر تاريخ يُدرَّس فيه)] بترتيب التوزيع."""
        rows = (
            Lesson.objects.filter(plan=plan, in_schedule=True)
            .values("code", "title")
            .annotate(last_end=Max("entries__week__end_date"))
            .order_by("last_end", "id")
        )
        return [(r["code"], r["title"], r["last_end"]) for r in rows]
