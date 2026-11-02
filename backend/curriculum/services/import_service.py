"""
استيراد ملفات الخطط الموحّدة (plans/<العام>/ف<الفصل>/*.xlsx) إلى نماذج Django.
تراكمي وIdempotent: كل خطة تُطابَق بهويتها الطبيعية (PLAN_KEY_FIELDS) فتُحدَّث ويُستبدل محتواها؛
والخطط غير الواردة في المصدر (فصول أو مواد أخرى) لا تُمس. مفتاح الخطة ثابت عبر الاستيراد،
فالصفوف المربوطة بها على المنصة تبقى مربوطة. كل الملفات تُفحص أولًا، ولا يُكتب شيء إن فشل أحدها.
"""
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from curriculum import models as m
from curriculum.domain.plan_spec import PlanFileError, PlanSpec
from curriculum.infrastructure.plan_workbook import plan_files, read_plan

# المحتوى التابع للخطة، بترتيب حذف آمن
PLAN_CHILDREN = (m.EnrichmentItem, m.ScheduleEntry, m.OutcomeBlock, m.CalendarEvent, m.Guideline,
                 m.TeachingStep, m.Lesson, m.Week, m.Unit)


@dataclass(frozen=True)
class ImportResult:
    plans: int
    lessons: int
    entries: int
    outcomes: int


class PlanImportService:
    def __init__(self, source: Path):
        self.files = plan_files(source)
        if not self.files:
            raise FileNotFoundError(f"no plan files in: {source}")

    def run(self) -> ImportResult:
        """يعيد إحصاء ما استُورد من هذا المصدر وحده."""
        specs, errors = [], []
        for f in self.files:
            try:
                specs.append(read_plan(f))
            except PlanFileError as exc:
                errors.append(str(exc))
        if errors:
            raise PlanFileError(f"{len(errors)} ملف", errors)
        return self.import_specs(specs)

    @transaction.atomic
    def import_specs(self, specs: list[PlanSpec]) -> ImportResult:
        plans = [self._write(s) for s in specs]
        self._prune_orphans()
        ids = [p.pk for p in plans]
        return ImportResult(
            plans=len(ids),
            lessons=m.Lesson.objects.filter(plan_id__in=ids).count(),
            entries=m.ScheduleEntry.objects.filter(plan_id__in=ids).count(),
            outcomes=m.LearningOutcome.objects.filter(block__plan_id__in=ids).count(),
        )

    # ------------------------------------------------------------- كتابة خطة

    @staticmethod
    def _upsert_plan(s: PlanSpec) -> m.Plan:
        src = s.source
        doc, _ = m.SourceDocument.objects.update_or_create(file_name=src.file_name, defaults={
            "form_code": src.form_code, "issue_no": src.issue_no, "issue_date": src.issue_date,
            "classification": src.classification, "department": src.department, "page_count": src.page_count})
        key = {f: getattr(s, f) for f in m.PLAN_KEY_FIELDS}
        plan, _ = m.Plan.objects.update_or_create(**key, defaults={"document": doc,
                                                                  "platform_class": s.platform_class})
        for model in PLAN_CHILDREN:
            model.objects.filter(plan=plan).delete()
        return plan

    def _write(self, s: PlanSpec) -> m.Plan:
        plan = self._upsert_plan(s)
        units = {u.unit_no: m.Unit.objects.create(plan=plan, unit_no=u.unit_no, title=u.title, domain=u.domain)
                 for u in s.units}
        weeks = {w.week_no: m.Week.objects.create(plan=plan, week_no=w.week_no, start_date=w.start_date,
                                                  end_date=w.end_date, week_type=w.week_type, note=w.note)
                 for w in s.weeks}
        lessons = {code: m.Lesson.objects.create(plan=plan, unit=units[unit_no], code=code, title=title,
                                                 in_schedule=in_schedule, total_periods=periods)
                   for unit_no, code, title, in_schedule, periods in s.lessons()}

        seq: dict[int, int] = {}
        entries = []
        for e in s.entries:
            seq[e.week_no] = seq.get(e.week_no, 0) + 1
            entries.append(m.ScheduleEntry(
                plan=plan, week=weeks[e.week_no], seq=seq[e.week_no], unit=units.get(e.unit_no),
                lesson=lessons.get(e.lesson_code), activity_type=e.activity_type, title=e.title, periods=e.periods))
        m.ScheduleEntry.objects.bulk_create(entries)

        for b in s.outcome_blocks:
            block = m.OutcomeBlock.objects.create(plan=plan, unit=units[b.unit_no],
                                                  week_from=b.week_from, week_to=b.week_to)
            block.competencies.set([m.Competency.objects.get_or_create(name=c)[0] for c in b.competencies])
            block.values.set([m.CoreValue.objects.get_or_create(name=v)[0] for v in b.values])
            m.LearningOutcome.objects.bulk_create([m.LearningOutcome(block=block, seq=i, text=t)
                                                   for i, t in enumerate(b.outcomes, 1)])

        m.CalendarEvent.objects.bulk_create([m.CalendarEvent(
            plan=plan, event_type=e.event_type, title=e.title, start_date=e.start_date, end_date=e.end_date,
            note=e.note) for e in s.events])
        m.EnrichmentItem.objects.bulk_create([m.EnrichmentItem(plan=plan, lesson=lessons[x.lesson_code],
                                                               detail=x.detail) for x in s.enrichment])
        m.Guideline.objects.bulk_create([m.Guideline(plan=plan, seq=i, title=t, body=b)
                                         for i, (t, b) in enumerate(s.guidelines, 1)])
        m.TeachingStep.objects.bulk_create([m.TeachingStep(plan=plan, seq=i, component=c, procedure=p)
                                            for i, (c, p) in enumerate(s.methodology, 1)])
        return plan

    @staticmethod
    def _prune_orphans():
        m.SourceDocument.objects.filter(plan__isnull=True).delete()
        m.Competency.objects.filter(outcomeblock__isnull=True).delete()
        m.CoreValue.objects.filter(outcomeblock__isnull=True).delete()
