"""
استيراد الخطط من قاعدة db/math_plans_2026_2027.db إلى نماذج Django.
Idempotent: كل تشغيل يستبدل بيانات الخطط بالكامل داخل transaction واحدة،
فالنتيجة نفسها مهما تكرر التشغيل. المصدر هو المرجع؛ تعديلات الإدارة تُستبدل.
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from curriculum import models as m


@dataclass(frozen=True)
class ImportResult:
    plans: int
    lessons: int
    entries: int
    outcomes: int


class PlanImportService:
    def __init__(self, source: Path):
        if not Path(source).is_file():
            raise FileNotFoundError(f"source db not found: {source}")
        self.source = Path(source)

    def run(self) -> ImportResult:
        src = sqlite3.connect(f"file:{self.source.as_posix()}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        try:
            with transaction.atomic():
                self._clear()
                self._load(src)
        finally:
            src.close()
        return ImportResult(
            plans=m.Plan.objects.count(),
            lessons=m.Lesson.objects.count(),
            entries=m.ScheduleEntry.objects.count(),
            outcomes=m.LearningOutcome.objects.count(),
        )

    @staticmethod
    def _clear():
        m.Plan.objects.all().delete()  # CASCADE لكل البيانات التابعة
        m.SourceDocument.objects.all().delete()
        m.Competency.objects.all().delete()
        m.CoreValue.objects.all().delete()

    def _load(self, src):
        q = lambda sql: src.execute(sql).fetchall()  # noqa: E731

        docs = {r["doc_id"]: m.SourceDocument.objects.create(
            form_code=r["form_code"], issue_no=r["issue_no"], issue_date=r["issue_date"],
            classification=r["classification"], department=r["department"],
            file_name=r["file_name"], page_count=r["page_count"],
        ) for r in q("SELECT * FROM source_documents")}

        plans = {r["plan_id"]: m.Plan.objects.create(
            document=docs[r["doc_id"]], subject=r["subject"], academic_year=r["academic_year"],
            term_no=r["term_no"], grade_level=r["grade_level"], tracks=r["tracks"] or "",
            shift=r["shift"], platform_class=r["platform_class"] or "",
        ) for r in q("SELECT * FROM plans")}

        units = {r["unit_id"]: m.Unit.objects.create(
            plan=plans[r["plan_id"]], unit_no=r["unit_no"], title=r["title"], domain=r["domain"],
        ) for r in q("SELECT * FROM units")}

        weeks = {r["week_id"]: m.Week.objects.create(
            plan=plans[r["plan_id"]], week_no=r["week_no"], start_date=r["start_date"],
            end_date=r["end_date"], week_type=r["week_type"], note=r["note"] or "",
        ) for r in q("SELECT * FROM weeks")}

        lessons = {r["lesson_id"]: m.Lesson.objects.create(
            plan=plans[r["plan_id"]], unit=units[r["unit_id"]], code=r["lesson_code"], title=r["title"],
            in_schedule=bool(r["in_schedule"]), total_periods=r["total_periods"],
        ) for r in q("SELECT * FROM lessons")}

        m.ScheduleEntry.objects.bulk_create([m.ScheduleEntry(
            plan=plans[r["plan_id"]], week=weeks[r["week_id"]], seq=r["seq"],
            unit=units.get(r["unit_id"]), lesson=lessons.get(r["lesson_id"]),
            activity_type=r["activity_type"], title=r["title"], periods=r["periods"],
        ) for r in q("SELECT * FROM schedule_entries")])

        comps = {r["competency_id"]: m.Competency.objects.create(name=r["name"])
                 for r in q("SELECT * FROM competencies")}
        vals = {r["value_id"]: m.CoreValue.objects.create(name=r["name"])
                for r in q("SELECT * FROM core_values")}

        blocks = {r["block_id"]: m.OutcomeBlock.objects.create(
            plan=plans[r["plan_id"]], unit=units[r["unit_id"]], week_from=r["week_from"], week_to=r["week_to"],
        ) for r in q("SELECT * FROM outcome_blocks")}
        for r in q("SELECT * FROM block_competencies"):
            blocks[r["block_id"]].competencies.add(comps[r["competency_id"]])
        for r in q("SELECT * FROM block_values"):
            blocks[r["block_id"]].values.add(vals[r["value_id"]])

        m.LearningOutcome.objects.bulk_create([m.LearningOutcome(
            block=blocks[r["block_id"]], seq=r["seq"], text=r["text"],
        ) for r in q("SELECT * FROM learning_outcomes")])

        m.CalendarEvent.objects.bulk_create([m.CalendarEvent(
            plan=plans[r["plan_id"]], event_type=r["event_type"], title=r["title"],
            start_date=r["start_date"], end_date=r["end_date"], note=r["note"] or "",
        ) for r in q("SELECT * FROM calendar_events")])

        m.EnrichmentItem.objects.bulk_create([m.EnrichmentItem(
            plan=plans[r["plan_id"]], lesson=lessons[r["lesson_id"]], detail=r["detail"] or "",
        ) for r in q("SELECT * FROM enrichment_items ORDER BY item_id")])

        m.Guideline.objects.bulk_create([m.Guideline(
            plan=plans[r["plan_id"]], seq=r["seq"], title=r["title"], body=r["body"],
        ) for r in q("SELECT * FROM guidelines")])

        m.TeachingStep.objects.bulk_create([m.TeachingStep(
            plan=plans[r["plan_id"]], seq=r["seq"], component=r["component"], procedure=r["procedure"],
        ) for r in q("SELECT * FROM teaching_methodology")])
