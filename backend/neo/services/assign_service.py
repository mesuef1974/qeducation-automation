"""
المهمة 2: إسناد التقييمات وفق تاريخ الدرس المرتبط بكل تقييم.
السياسة (settings.NEO_ASSIGN_POLICY): يظهر التقييم صباح يوم الدرس ويستحق بعد N يوم؛
الدرس الماضي يُعطى المهلة نفسها محسوبة من اليوم. المُسند مسبقًا لا يُمس، ولا مواعيد قائمة على المنصة
تخالف المعتمد (إضافة فقط، قرار المعلم): تُنبَّه للمراجعة.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from neo.domain.redact import scrub
from neo.domain.types import ParsedAssessment
from neo.infrastructure.client import NeoClient, NotLoggedIn, stamp
from neo.infrastructure.parsers import parse_assessments
from neo.models import (
    AssignProposal,
    PlatformAssessment,
    PlatformClass,
    PlatformLesson,
    SyncRun,
)
from neo.services import live, safety

FLAG_PAST_LESSON = "درس ماضٍ - المهلة من اليوم"
AUTO_GIVE_NOTE = "المواعيد مضبوطة؛ تُسنده المنصة تلقائيًا حين يصير درسه الحالي"
KEPT_NOTE = "على المنصة مواعيد تخالف المعتمد فلم تُمس؛ راجعها على المنصة"


def _window(begin: datetime, end: datetime) -> tuple:
    """(البداية، الاستحقاق) بتوقيت قطر للمقارنة بما تعرضه المنصة."""
    b, e = (timezone.localtime(t).replace(tzinfo=None) for t in (begin, end))
    return stamp(f"{b:%Y-%m-%d %H:%M}"), stamp(f"{e:%Y-%m-%d %H:%M}")


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
        given, undated, unconfirmed, drafts = [], [], [], []
        for a in PlatformAssessment.objects.filter(klass=klass):
            lesson = lessons.get(a.lms_lesson_id)
            if a.given:
                given.append(a.title)
            elif not lesson or not lesson.date:
                undated.append(a.title)
            elif not lesson.match_sure:  # الخطوة 1: مطابقة درسه غير مؤكدة، فيُستبعد وينبَّه عليه
                unconfirmed.append(f"{a.title} ← {safety.unconfirmed_label(lesson)}")
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
            "unconfirmed_match": unconfirmed,
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
        return safety.mark_approved(qs)

    # ------------------------------------------------------------- تطبيق

    def apply(self, run: SyncRun, client_factory: Callable[[], NeoClient], today: date,
              limit: int | None = None) -> SyncRun:
        """
        يضبط المواعيد لكل المعتمد، ويُسند يدويًا تقييمات الدروس الماضية فقط. تقييمات اليوم وما بعده
        تُسندها المنصة تلقائيًا حين يصير درسها «الحالي» (auto_give_assignments + set_current_when_started)،
        والمنصة ترفض إسناد تقييم درس بعد الدرس الحالي أصلًا.
        الخطوة 5: تُقرأ مواعيد كل تقييم قبل الكتابة وبعدها: المضبوط كما اعتُمد لا يُعاد، والمواعيد القائمة المخالفة للمعتمد
        (يدوية أو كتبتها الأتمتة سابقًا) لا تُمس وتُنبَّه (إضافة فقط، قرار المعلم). ولا يُعدّ «مطبّقًا» إلا إذا
        طابقت القراءة البعدية المعتمد. أول خطأ غير متوقع يوقف التطبيق كله ولا إسناد بعده، ويوم غير المعتمد
        ولا السابق على المنصة (كتابة خاطئة) يوقف الكتابة كلها بمفتاح الإيقاف الآلي.
        """
        lms_id = run.klass.lms_id
        items = list(run.assign_proposals.filter(status=AssignProposal.Status.APPROVED)
                     .select_related("assessment").order_by("lesson_date", "pk")[:limit])
        results: dict[int, tuple[str, str]] = {}
        session_error, stop, wrong = None, "", ""
        ours = {prev.assessment.lms_assignment_id: _window(prev.begin_at, prev.end_at)  # آخر ما كتبته الأتمتة
                for prev in AssignProposal.objects.filter(run__klass=run.klass, status=AssignProposal.Status.APPLIED)
                .select_related("assessment").order_by("applied_at")}
        kept: list[str] = []
        with client_factory() as client:  # لا ORM هنا
            state = {a.lms_assignment_id: a.given for a in parse_assessments(client.assessments_html(lms_id))}
            to_give = []
            for i, p in enumerate(items, 1):
                live.step(f"مواعيد: {p.assessment.title}", i, len(items))
                aid = p.assessment.lms_assignment_id
                if state.get(aid):
                    results[p.pk] = (AssignProposal.Status.SKIPPED, "مُسند على المنصة")
                    continue
                begin, end = (timezone.localtime(t).replace(tzinfo=None) for t in (p.begin_at, p.end_at))
                want = _window(p.begin_at, p.end_at)
                try:
                    before_raw = client.assessment_window(aid)
                    before = tuple(stamp(v) for v in before_raw)
                    if before != want and any(before):  # إضافة فقط: مواعيد قائمة مخالفة لا تُمس
                        who = "كتبتها الأتمتة سابقًا" if ours.get(aid) == before else "ضُبطت يدويًا"
                        results[p.pk] = (AssignProposal.Status.SKIPPED,
                                         f"{KEPT_NOTE} ({who}: {before_raw[0]} ← {before_raw[1]})")
                        kept.append(f"{p.assessment.title}: {before_raw[0]} ← {before_raw[1]}")
                        continue
                    if before != want:
                        client.set_assessment_window(aid, begin, end, p.allow_late)
                        shown = client.assessment_window(aid)
                        after = tuple(stamp(v) for v in shown)
                        if after != want:
                            if after == before:
                                results[p.pk] = (AssignProposal.Status.FAILED,
                                                 "لم تثبت المواعيد بعد الحفظ (القراءة البعدية كما قبلها)")
                            else:
                                diff = (f"{p.assessment.title}: المعتمد {begin:%Y-%m-%d %H:%M} ← {end:%Y-%m-%d %H:%M}، "
                                        f"والمنصة {shown[0]} ← {shown[1]}")
                                results[p.pk] = (AssignProposal.Status.FAILED, f"كتابة غير مطابقة: {diff}")
                                if [x and x[:3] for x in after] != [x and x[:3] for x in want]:  # يوم غير المعتمد
                                    wrong = diff
                            stop = results[p.pk][1]
                            break
                    to_give.append(p)
                except NotLoggedIn as exc:
                    session_error = exc
                    break
                except Exception as exc:  # noqa: BLE001 - أول خطأ غير متوقع يوقف التطبيق
                    results[p.pk] = (AssignProposal.Status.FAILED, f"ضبط المواعيد: {scrub(str(exc))[:400]}")
                    stop = results[p.pk][1]
                    break
            for p in [p for p in to_give if p.lesson_date >= today]:
                results[p.pk] = (AssignProposal.Status.APPLIED, AUTO_GIVE_NOTE)
            to_give = [p for p in to_give if p.lesson_date < today]
            if to_give and not session_error and not stop:
                try:
                    client.give_assessments(lms_id, [p.assessment.lms_assignment_id for p in to_give])
                except Exception as exc:  # noqa: BLE001 - نتحقق من الحالة الفعلية أدناه
                    give_error = scrub(str(exc))[:400]
                else:
                    give_error = ""
                after = {a.lms_assignment_id: a.given for a in parse_assessments(client.assessments_html(lms_id))}
                for p in to_give:
                    ok = after.get(p.assessment.lms_assignment_id)
                    results[p.pk] = ((AssignProposal.Status.APPLIED, "") if ok else
                                     (AssignProposal.Status.FAILED, give_error or "لم يظهر مُسندًا بعد الإسناد"))
        if kept:
            live.emit("warn", f"مواعيد قائمة على المنصة لم تُمس ({len(kept)}): {kept[0]}")
        log = self._record(run, items, results, session_error, stop, kept)
        if wrong:
            safety.halt(f"كتابة خاطئة في مواعيد التقييمات · {run.klass}: {wrong}")
        if session_error:
            raise session_error
        return log

    @transaction.atomic
    def _record(self, run, items, results, session_error, stop: str = "", kept: list[str] | None = None) -> SyncRun:
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
        if stop:
            summary.update(stopped=stop, not_attempted=sum(1 for p in items if p.pk not in results))
        if kept:
            summary["kept_on_platform"] = kept
        return SyncRun.objects.create(
            klass=run.klass, kind=SyncRun.Kind.ASSIGN_APPLY, summary=summary, finished_at=timezone.now(),
            ok=not session_error and not stats.get(AssignProposal.Status.FAILED))
