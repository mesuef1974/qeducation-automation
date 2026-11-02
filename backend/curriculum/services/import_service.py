"""
استيراد الخطط من قاعدة مصدر (يبنيها db/build_db.py) إلى نماذج Django.
تراكمي وIdempotent: كل خطة في المصدر تُطابَق بهويتها الطبيعية (PLAN_KEY_FIELDS) فتُحدَّث
ويُستبدل محتواها؛ والخطط غير الموجودة في المصدر (فصول أو مواد أخرى) لا تُمس.
مفتاح الخطة ثابت عبر الاستيراد، فالصفوف المربوطة بها على المنصة تبقى مربوطة.
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from curriculum import models as m

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
        if not Path(source).is_file():
            raise FileNotFoundError(f"source db not found: {source}")
        self.source = Path(source)

    def run(self) -> ImportResult:
        """يعيد إحصاء ما استُورد من هذا المصدر وحده."""
        src = sqlite3.connect(f"file:{self.source.as_posix()}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        try:
            with transaction.atomic():
                plans = self._load(src)
                self._prune_orphans()
        finally:
            src.close()
        ids = [p.pk for p in plans]
        return ImportResult(
            plans=len(ids),
            lessons=m.Lesson.objects.filter(plan_id__in=ids).count(),
            entries=m.ScheduleEntry.objects.filter(plan_id__in=ids).count(),
            outcomes=m.LearningOutcome.objects.filter(block__plan_id__in=ids).count(),
        )

    @staticmethod
    def _upsert_plan(doc: m.SourceDocument, r) -> m.Plan:
        key = {"subject": r["subject"], "academic_year": r["academic_year"], "term_no": r["term_no"],
               "grade_level": r["grade_level"], "tracks": r["tracks"] or "", "shift": r["shift"]}
        plan, _ = m.Plan.objects.update_or_create(
            **key, defaults={"document": doc, "platform_class": r["platform_class"] or ""})
        for model in PLAN_CHILDREN:
            model.objects.filter(plan=plan).delete()
        return plan

    @staticmethod
    def _prune_orphans():
        m.SourceDocument.objects.filter(plan__isnull=True).delete()
        m.Competency.objects.filter(outcomeblock__isnull=True).delete()
        m.CoreValue.objects.filter(outcomeblock__isnull=True).delete()

    def _load(self, src):
        q = lambda sql: src.execute(sql).fetchall()  # noqa: E731

        docs = {r["doc_id"]: m.SourceDocument.objects.update_or_create(
            file_name=r["file_name"], defaults={
                "form_code": r["form_code"], "issue_no": r["issue_no"], "issue_date": r["issue_date"],
                "classification": r["classification"], "department": r["department"],
                "page_count": r["page_count"]},
        )[0] for r in q("SELECT * FROM source_documents")}

        plans = {r["plan_id"]: self._upsert_plan(docs[r["doc_id"]], r) for r in q("SELECT * FROM plans")}

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

        comps = {r["competency_id"]: m.Competency.objects.get_or_create(name=r["name"])[0]
                 for r in q("SELECT * FROM competencies")}
        vals = {r["value_id"]: m.CoreValue.objects.get_or_create(name=r["name"])[0]
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
        return list(plans.values())
