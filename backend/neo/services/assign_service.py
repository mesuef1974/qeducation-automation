"""
المهمة 2: إسناد التقييمات وفق تاريخ الدرس المرتبط بكل تقييم.
السياسة (settings.NEO_ASSIGN_POLICY): يظهر التقييم صباح يوم الدرس ويستحق بعد N يوم؛
الدرس الماضي يُعطى المهلة نفسها محسوبة من اليوم. المُسند مسبقًا لا يُمس.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from neo.domain.types import ParsedAssessment
from neo.infrastructure.client import NeoClient, NotLoggedIn
from neo.infrastructure.parsers import parse_assessments
from neo.models import AssignProposal, PlatformAssessment, PlatformClass, PlatformLesson, SyncRun
from neo.services import live

FLAG_PAST_LESSON = "درس ماضٍ - المهلة من اليوم"
AUTO_GIVE_NOTE = "المواعيد مضبوطة؛ تُسنده المنصة تلقائيًا حين يصير درسه الحالي"


@dataclass(frozen=True)
class AssignPolicy:
    begin_time: time = time(7, 0)
    due_days: int = 2
    due_time: time = time(23, 59)
    allow_late: bool = True


def policy() -> AssignPolicy:
    return AssignPolicy(**getattr(settings, "NEO_ASSIGN_POLICY", {}))


def plan_window(lesson_date: date, today: date, p: AssignPolicy) -> tuple[datetime, datetime, list[str]]:
    """منطق نقي: (البداية، الاستحقاق، تنبيهات) بتوقيت قطر."""
    base = max(lesson_date, today)
    tz = timezone.get_default_timezone()
    begin = datetime.combine(base, p.begin_time, tzinfo=tz)
    end = datetime.combine(base + timedelta(days=p.due_days), p.due_time, tzinfo=tz)
    return begin, end, [FLAG_PAST_LESSON] if lesson_date < today else []


class AssignService:
    # ------------------------------------------------------------- جلب

    def fetch(self, classes: list[PlatformClass], client_factory: Callable[[], NeoClient]) -> None:
        with client_factory() as client:  # لا ORM داخل Playwright
            pages = {k.pk: client.assessments_html(k.lms_id) for k in classes}
        for k in classes:
            self.ingest(k, parse_assessments(pages[k.pk]))

    @transaction.atomic
    def ingest(self, klass: PlatformClass, items: list[ParsedAssessment]) -> None:
        now = timezone.now()
        for a in items:
            PlatformAssessment.objects.update_or_create(
                lms_assignment_id=a.lms_assignment_id,
                defaults={"klass": klass, "title": a.title, "lms_lesson_id": a.lms_lesson_id,
                          "given": a.given, "fetched_at": now},
            )
        PlatformAssessment.objects.filter(klass=klass).exclude(
            lms_assignment_id__in=[a.lms_assignment_id for a in items]).delete()

    # ------------------------------------------------------------- اقتراح

    @transaction.atomic
    def plan(self, klass: PlatformClass, today: date) -> SyncRun:
        p = policy()
        AssignProposal.objects.filter(run__klass=klass, status__in=[
            AssignProposal.Status.PENDING, AssignProposal.Status.APPROVED,
        ]).update(status=AssignProposal.Status.REJECTED, error="استُبدل بعملية اقتراح أحدث")
        run = SyncRun.objects.create(klass=klass, kind=SyncRun.Kind.ASSIGN_PLAN)

        lessons = {pl.lms_lesson_id: pl for pl in PlatformLesson.objects.filter(klass=klass)}
        given, undated, drafts = [], [], []
        for a in PlatformAssessment.objects.filter(klass=klass):
            lesson = lessons.get(a.lms_lesson_id)
            if a.given:
                given.append(a.title)
            elif not lesson or not lesson.date:
                undated.append(a.title)
            else:
                begin, end, flags = plan_window(lesson.date, today, p)
                drafts.append(AssignProposal(run=run, assessment=a, lesson_date=lesson.date, begin_at=begin,
                                             end_at=end, allow_late=p.allow_late, flags="، ".join(flags)))
        AssignProposal.objects.bulk_create(drafts)
        run.summary = {
            "proposals": len(drafts),
            "past_lessons": sum(1 for d in drafts if d.flags),
            "already_given": given,
            "no_lesson_date": undated,
            "policy": {"begin": p.begin_time.isoformat("minutes"), "due_days": p.due_days,
                       "due": p.due_time.isoformat("minutes"), "allow_late": p.allow_late},
        }
        run.ok, run.finished_at = True, timezone.now()
        run.save()
        return run

    def approve(self, run_id: int, only_lesson_from: date | None = None) -> int:
        qs = AssignProposal.objects.filter(run_id=run_id, status=AssignProposal.Status.PENDING)
        if only_lesson_from:
            qs = qs.filter(lesson_date__gte=only_lesson_from)
        return qs.update(status=AssignProposal.Status.APPROVED)

    # ------------------------------------------------------------- تطبيق

    def apply(self, run: SyncRun, client_factory: Callable[[], NeoClient], today: date,
              limit: int | None = None) -> SyncRun:
        """
        يضبط المواعيد لكل المعتمد، ويُسند يدويًا تقييمات الدروس الماضية فقط. تقييمات اليوم وما بعده
        تُسندها المنصة تلقائيًا حين يصير درسها «الحالي» (auto_give_assignments + set_current_when_started)،
        والمنصة ترفض إسناد تقييم درس بعد الدرس الحالي أصلًا.
        """
        lms_id = run.klass.lms_id
        items = list(run.assign_proposals.filter(status=AssignProposal.Status.APPROVED)
                     .select_related("assessment").order_by("lesson_date", "pk")[:limit])
        results: dict[int, tuple[str, str]] = {}
        session_error = None
        with client_factory() as client:  # لا ORM هنا
            state = {a.lms_assignment_id: a.given for a in parse_assessments(client.assessments_html(lms_id))}
            to_give = []
            for i, p in enumerate(items, 1):
                live.step(f"مواعيد: {p.assessment.title}", i, len(items))
                aid = p.assessment.lms_assignment_id
                if state.get(aid):
                    results[p.pk] = (AssignProposal.Status.SKIPPED, "مُسند على المنصة")
                    continue
                try:
                    client.set_assessment_window(aid, timezone.localtime(p.begin_at).replace(tzinfo=None),
                                                 timezone.localtime(p.end_at).replace(tzinfo=None), p.allow_late)
                    to_give.append(p)
                except NotLoggedIn as exc:
                    session_error = exc
                    break
                except Exception as exc:  # noqa: BLE001
                    results[p.pk] = (AssignProposal.Status.FAILED, f"ضبط المواعيد: {str(exc)[:400]}")
            for p in [p for p in to_give if p.lesson_date >= today]:
                results[p.pk] = (AssignProposal.Status.APPLIED, AUTO_GIVE_NOTE)
            to_give = [p for p in to_give if p.lesson_date < today]
            if to_give and not session_error:
                try:
                    client.give_assessments(lms_id, [p.assessment.lms_assignment_id for p in to_give])
                except Exception as exc:  # noqa: BLE001 - نتحقق من الحالة الفعلية أدناه
                    give_error = str(exc)[:400]
                else:
                    give_error = ""
                after = {a.lms_assignment_id: a.given for a in parse_assessments(client.assessments_html(lms_id))}
                for p in to_give:
                    ok = after.get(p.assessment.lms_assignment_id)
                    results[p.pk] = ((AssignProposal.Status.APPLIED, "") if ok else
                                     (AssignProposal.Status.FAILED, give_error or "لم يظهر مُسندًا بعد الإسناد"))
        log = self._record(run, items, results, session_error)
        if session_error:
            raise session_error
        return log

    @transaction.atomic
    def _record(self, run, items, results, session_error) -> SyncRun:
        now = timezone.now()
        stats: dict[str, int] = {}
        for p in items:
            if p.pk not in results:
                continue
            p.status, p.error = results[p.pk]
            if p.status == AssignProposal.Status.APPLIED:
                p.applied_at = now
                if p.error != AUTO_GIVE_NOTE:
                    PlatformAssessment.objects.filter(pk=p.assessment_id).update(given=True)
            p.save(update_fields=["status", "error", "applied_at"])
            stats[p.status] = stats.get(p.status, 0) + 1
        summary = {"plan_run": run.pk, **stats}
        if session_error:
            summary["error"] = "انتهت الجلسة"
        return SyncRun.objects.create(
            klass=run.klass, kind=SyncRun.Kind.ASSIGN_APPLY, summary=summary, finished_at=timezone.now(),
            ok=not session_error and not stats.get(AssignProposal.Status.FAILED))
