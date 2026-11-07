"""خطة مخزّنة ← PlanSpec (للتصدير إلى ملف خطة أو مقارنة ذهاب وإياب)."""
from django.db.models import Sum

from curriculum import models as m
from curriculum.domain.plan_spec import (
    EnrichmentSpec,
    EntrySpec,
    EventSpec,
    ExtraLessonSpec,
    OutcomeBlockSpec,
    PlanSpec,
    SourceInfo,
    UnitSpec,
    WeekSpec,
)


def spec_from_plan(plan: m.Plan) -> PlanSpec:
    d = plan.document
    totals = {r["week__week_no"]: r["s"] for r in
              m.ScheduleEntry.objects.filter(plan=plan).values("week__week_no").annotate(s=Sum("periods"))}
    entries = m.ScheduleEntry.objects.filter(plan=plan).select_related("week", "unit", "lesson") \
        .order_by("week__week_no", "seq")
    blocks = m.OutcomeBlock.objects.filter(plan=plan).select_related("unit") \
        .prefetch_related("competencies", "values", "outcomes").order_by("pk")
    return PlanSpec(
        subject=plan.subject, academic_year=plan.academic_year, term_no=plan.term_no,
        grade_level=plan.grade_level, shift=plan.shift, tracks=plan.tracks, platform_class=plan.platform_class,
        source=SourceInfo(file_name=d.file_name, page_count=d.page_count, form_code=d.form_code,
                          issue_no=d.issue_no, issue_date=d.issue_date, classification=d.classification,
                          department=d.department),
        weeks=tuple(WeekSpec(w.week_no, w.start_date, w.end_date, w.week_type, w.note, totals.get(w.week_no, 0))
                    for w in plan.weeks.order_by("week_no")),
        units=tuple(UnitSpec(u.unit_no, u.title, u.domain) for u in plan.units.order_by("unit_no")),
        entries=tuple(EntrySpec(e.week.week_no, e.unit.unit_no if e.unit else None, e.activity_type,
                                e.lesson.code if e.lesson else None, e.title, e.periods) for e in entries),
        extra_lessons=tuple(ExtraLessonSpec(x.unit.unit_no, x.code, x.title)
                            for x in plan.lessons.filter(in_schedule=False).select_related("unit").order_by("pk")),
        outcome_blocks=tuple(OutcomeBlockSpec(
            b.unit.unit_no, b.week_from, b.week_to, tuple(c.name for c in b.competencies.all()),
            tuple(v.name for v in b.values.all()), tuple(o.text for o in b.outcomes.order_by("seq")),
        ) for b in blocks),
        enrichment=tuple(EnrichmentSpec(x.lesson.code, x.detail)
                         for x in plan.enrichment.select_related("lesson").order_by("pk")),
        events=tuple(EventSpec(e.event_type, e.title, e.start_date, e.end_date, e.note)
                     for e in plan.events.order_by("start_date", "pk")),
        guidelines=tuple((g.title, g.body) for g in plan.guidelines.order_by("seq")),
        methodology=tuple((s.component, s.procedure) for s in plan.methodology.order_by("seq")),
    )


def default_file_name(spec: PlanSpec) -> str:
    """مسار مقترح داخل مجلد الخطط: <العام>/ف<الفصل>/<المادة>_<المستوى>[_<المسارات>].xlsx"""
    tracks = f"_{spec.tracks.replace(' ', '-')}" if spec.tracks else ""
    return f"{spec.academic_year}/ف{spec.term_no}/{spec.subject}_{spec.grade_level}{tracks}.xlsx"
