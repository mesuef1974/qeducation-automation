"""
تنسيق المزامنة: جلب الدروس ← مطابقتها بالخطة ← اقتراح التواريخ ← تطبيق المعتمد منها.
كل خطوة تُسجَّل في SyncRun (Audit Trail). التطبيق لا يكتب إلا الاقتراحات المعتمدة،
ولا يمس درسًا له تاريخ على المنصة (Idempotent وآمن على التعديلات اليدوية).
"""
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date

from django.db import transaction
from django.utils import timezone

from curriculum.models import Plan, ScheduleEntry
from neo.domain.types import ParsedLesson, ParsedSlot, Target
from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.infrastructure.parsers import parse_lessons, parse_timetable
from neo.models import DateProposal, PlatformClass, PlatformLesson, SyncRun, TimetableSlot
from neo.services.matching import match_sequence
from neo.services.scheduling import LessonState, WeekSpan, build_slots, propose_dates

NO_MATCH = "-"


def build_targets(plan: Plan) -> list[Target]:
    weeks, periods, first, titles, is_lesson = defaultdict(set), Counter(), {}, {}, {}
    entries = ScheduleEntry.objects.filter(plan=plan).select_related("week", "lesson", "unit")
    for i, e in enumerate(entries.order_by("week__week_no", "seq")):
        code = e.lesson.code if e.lesson else f"{e.activity_type}#{e.unit.unit_no if e.unit else 0}"
        weeks[code].add(e.week.week_no)
        periods[code] += e.periods
        first.setdefault(code, i)
        titles[code] = e.lesson.title if e.lesson else e.title
        is_lesson[code] = e.lesson is not None
    return [Target(c, titles[c], first[c], frozenset(weeks[c]), periods[c], is_lesson[c]) for c in first]


class NoActiveClasses(LookupError):
    pass


def active_classes(lms_ids: list[int] | None = None) -> list[PlatformClass]:
    """الصفوف المفعّلة (أو المحددة منها). تُدار من لوحة الإدارة أو بأمر neo_class."""
    qs = PlatformClass.objects.active()
    if lms_ids:
        qs = qs.filter(lms_id__in=lms_ids)
        missing = set(lms_ids) - set(qs.values_list("lms_id", flat=True))
        if missing:
            raise NoActiveClasses(f"صفوف غير مسجلة أو غير مفعّلة: {sorted(missing)}")
    classes = list(qs)
    if not classes:
        raise NoActiveClasses("لا توجد صفوف مفعّلة؛ أضف صفًا: python manage.py neo_class add LMS_ID --plan PLAN_ID")
    return classes


class SyncService:

    # ------------------------------------------------------------- جلب

    def fetch(self, classes: list[PlatformClass], client_factory: Callable[[], NeoClient]) -> list[SyncRun]:
        # Playwright (sync) يشغّل حلقة أحداث تمنع ORM داخلها؛ نجمع الصفحات أولًا ثم نحفظ بعد الإغلاق
        years = {k.pk: k.plan.academic_year for k in classes}
        pages = {}
        with client_factory() as client:
            for k in classes:
                pages[k.pk] = (client.lesson_list_html(k.lms_id), client.timetable_html(k.lms_id))
        parsed = {k.pk: (parse_lessons(pages[k.pk][0], years[k.pk]), parse_timetable(pages[k.pk][1])) for k in classes}
        empty = [k.name for k in classes if not parsed[k.pk][0]]
        if empty:  # صفحة غير متوقعة؛ لا نحذف بيانات محلية بناءً عليها
            raise PlatformError(f"لم يُعثر على دروس في: {', '.join(empty)}")
        return [self.ingest(k, *parsed[k.pk]) for k in classes]

    @transaction.atomic
    def ingest(self, klass: PlatformClass, lessons: list[ParsedLesson], slots: list[ParsedSlot]) -> SyncRun:
        now = timezone.now()
        seen = []
        for p in lessons:
            PlatformLesson.objects.update_or_create(
                lms_lesson_id=p.lms_lesson_id,
                defaults={"klass": klass, "position": p.position, "title": p.title,
                          "description": p.description, "date": p.date, "period": p.period, "fetched_at": now},
            )
            seen.append(p.lms_lesson_id)
        removed, _ = PlatformLesson.objects.filter(klass=klass).exclude(lms_lesson_id__in=seen).delete()
        if slots:
            TimetableSlot.objects.filter(klass=klass).delete()
            TimetableSlot.objects.bulk_create([TimetableSlot(klass=klass, weekday=s.weekday, period=s.period)
                                               for s in set(slots)])
        klass.last_fetched_at = now
        klass.save(update_fields=["last_fetched_at"])
        return SyncRun.objects.create(
            klass=klass, kind=SyncRun.Kind.FETCH, ok=True, finished_at=timezone.now(),
            summary={"lessons": len(lessons), "dated": sum(1 for p in lessons if p.date),
                     "removed": removed, "slots": len(slots)},
        )

    # ------------------------------------------------------------- اقتراح

    @transaction.atomic
    def plan(self, klass: PlatformClass, today: date) -> SyncRun:
        plan = klass.plan
        targets = build_targets(plan)
        by_code = {t.code: t for t in targets}
        lessons = list(PlatformLesson.objects.filter(klass=klass).order_by("position"))

        for pl, m in zip(lessons, match_sequence([pl.title for pl in lessons], targets)):
            pl.match_code, pl.match_score = m.code or "", m.score
        PlatformLesson.objects.bulk_update(lessons, ["match_code", "match_score"])

        def code_of(pl):
            c = pl.effective_code
            return None if not c or c == NO_MATCH else c

        weeks = [WeekSpan(w.week_no, w.start_date, w.week_type == "تدريس") for w in plan.weeks.order_by("week_no")]
        timetable = list(klass.slots.values_list("weekday", "period"))
        slots = build_slots(weeks, timetable)
        drafts, overflow = propose_dates(
            [LessonState(pl.pk, pl.date, pl.period, code_of(pl)) for pl in lessons], by_code, slots, today)

        # الاقتراحات المعلّقة من عمليات سابقة تُستبدل؛ يبقى مصدر واحد للمراجعة
        DateProposal.objects.filter(run__klass=klass, status__in=[
            DateProposal.Status.PENDING, DateProposal.Status.APPROVED,
        ]).update(status=DateProposal.Status.REJECTED, error="استُبدل بعملية اقتراح أحدث")
        run = SyncRun.objects.create(klass=klass, kind=SyncRun.Kind.PLAN)
        DateProposal.objects.bulk_create([DateProposal(
            run=run, lesson_id=d.lesson_id, proposed_date=d.slot.date, proposed_period=d.slot.period,
            plan_week_no=d.slot.week_no, flags="، ".join(d.flags),
        ) for d in drafts])

        run.summary = self._plan_report(lessons, targets, code_of, drafts, overflow, slots)
        run.ok, run.finished_at = True, timezone.now()
        run.save()
        return run

    @staticmethod
    def _plan_report(lessons, targets, code_of, drafts, overflow, slots) -> dict:
        counts = Counter(code_of(pl) for pl in lessons)
        week_of = {s.date: s.week_no for s in slots}
        off_plan = [
            f"{pl.position}. {pl.title} ({pl.date:%m-%d}، أسبوع {week_of.get(pl.date, '-')})"
            for pl in lessons
            if pl.date and code_of(pl) and week_of.get(pl.date) not in next(
                (t.weeks for t in targets if t.code == code_of(pl)), frozenset())
        ]
        return {
            "proposals": len(drafts),
            "flags": dict(Counter(f for d in drafts for f in d.flags)),
            "overflow": len(overflow),
            "unmatched": [f"{pl.position}. {pl.title}" for pl in lessons if not code_of(pl)],
            "missing_in_platform": [f"{t.code} {t.title}" for t in targets if t.code not in counts],
            "count_mismatch": [
                f"{t.code} {t.title}: المنصة {counts[t.code]} / الخطة {t.plan_periods}"
                for t in targets if t.is_lesson and t.code in counts and counts[t.code] != t.plan_periods
            ],
            "dated_outside_plan_weeks": off_plan,
        }

    # ------------------------------------------------------------- تطبيق

    def approve(self, run_id: int, only_from: date | None = None) -> int:
        qs = DateProposal.objects.filter(run_id=run_id, status=DateProposal.Status.PENDING)
        if only_from:
            qs = qs.filter(proposed_date__gte=only_from)
        return qs.update(status=DateProposal.Status.APPROVED)

    def apply(self, run: SyncRun, client_factory: Callable[[], NeoClient]) -> SyncRun:
        lms_id = run.klass.lms_id
        items = list(run.proposals.filter(status=DateProposal.Status.APPROVED).select_related("lesson"))
        results: dict[int, tuple[str, str]] = {}
        session_error = None
        # مرحلة المنصة: لا ORM هنا (انظر fetch)
        with client_factory() as client:
            for p in items:
                lid = p.lesson.lms_lesson_id
                try:
                    if client.lesson_has_date(lms_id, lid):
                        results[p.pk] = (DateProposal.Status.SKIPPED, "للدرس تاريخ على المنصة")
                    else:
                        client.set_lesson_date(lms_id, lid, p.proposed_date, p.proposed_period)
                        results[p.pk] = (DateProposal.Status.APPLIED, "")
                except NotLoggedIn as exc:
                    session_error = exc
                    break
                except Exception as exc:  # noqa: BLE001 - نسجّل ونكمل بقية الدروس
                    results[p.pk] = (DateProposal.Status.FAILED, str(exc)[:500])
        log = self._record_apply(run, items, results, session_error)  # يحفظ ما تم قبل انقطاع الجلسة
        if session_error:
            raise session_error
        return log

    @transaction.atomic
    def _record_apply(self, run, items, results, session_error) -> SyncRun:
        now = timezone.now()
        stats = Counter()
        for p in items:
            if p.pk not in results:
                continue
            p.status, p.error = results[p.pk]
            if p.status == DateProposal.Status.APPLIED:
                p.applied_at = now
                PlatformLesson.objects.filter(pk=p.lesson_id).update(date=p.proposed_date, period=p.proposed_period)
            p.save(update_fields=["status", "error", "applied_at"])
            stats[p.status] += 1
        summary = {"plan_run": run.pk, **stats}
        if session_error:
            summary["error"] = "انتهت الجلسة"
        log = SyncRun.objects.create(
            klass=run.klass, kind=SyncRun.Kind.APPLY, summary=summary, finished_at=timezone.now(),
            ok=not session_error and stats[DateProposal.Status.FAILED] == 0)
        return log
