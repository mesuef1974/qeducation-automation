"""
مركز المراجعة: قرارات المعلم على الاقتراحات بأنواعها الثلاثة، وملخص كل صف لشاشة «اليوم».
لا يلمس المنصة؛ التطبيق يمر دائمًا بمهمة (JobService).
"""
from datetime import date

from django.db.models import Count, Q

from neo.models import PlatformClass, PlatformLesson, ProposalStatus, SyncRun
from neo.services import safety
from neo.services.pipeline import PROPOSALS

# القرار ← (الحالات التي يقبلها، الحالة الناتجة)
DECISIONS = {
    "approve": ((ProposalStatus.PENDING,), ProposalStatus.APPROVED),
    "reject": ((ProposalStatus.PENDING, ProposalStatus.APPROVED), ProposalStatus.REJECTED),
    "reset": ((ProposalStatus.APPROVED,), ProposalStatus.PENDING),
}
# عملية الاقتراح لكل نوع
PLAN_KIND = {"date": SyncRun.Kind.PLAN, "assign": SyncRun.Kind.ASSIGN_PLAN, "publish": SyncRun.Kind.PUBLISH_PLAN,
             "content": SyncRun.Kind.CONTENT_PLAN}


def decide(kind: str, ids: list[int], decision: str) -> int:
    """
    يغيّر حالة الاقتراحات المسموح بها فقط؛ يعيد عدد ما تغيّر (تكرار الطلب لا يغيّر شيئًا). الاعتماد يسجّل وقته
    وبصمة الدرس (الخطوة 4)، ولا يُعتمد ما مطابقة درسه غير مؤكدة.
    """
    accepts, to = DECISIONS[decision]
    qs = PROPOSALS[kind].objects.filter(pk__in=ids, status__in=accepts)
    if to == ProposalStatus.APPROVED:
        return safety.mark_approved(qs)
    return qs.update(status=to, approved_at=None, approved_fp="")


def _lesson(pl: PlatformLesson) -> dict:
    return {"id": pl.lms_lesson_id, "position": pl.position, "title": pl.title, "date": pl.date, "period": pl.period}


def class_overview(klass: PlatformClass, today: date) -> dict:
    lessons = PlatformLesson.objects.filter(klass=klass)
    counts = lessons.aggregate(total=Count("pk"), dated=Count("pk", filter=Q(date__isnull=False)),
                               hidden=Count("pk", filter=Q(hidden=True)),
                               points=Count("pk", filter=Q(awards_points=True)))
    review = {}
    for kind, model in PROPOSALS.items():
        by = dict(model.objects.filter(run__klass=klass, status__in=[ProposalStatus.PENDING, ProposalStatus.APPROVED])
                  .values_list("status").annotate(n=Count("pk")))
        latest = klass.runs.filter(kind=PLAN_KIND[kind]).values_list("pk", flat=True).first()
        review[kind] = {"pending": by.get(ProposalStatus.PENDING, 0), "approved": by.get(ProposalStatus.APPROVED, 0),
                        "latest_run": latest}
    verify = klass.runs.filter(kind=SyncRun.Kind.VERIFY).first()
    return {
        "prep": prep_overview(klass, today),
        "lessons": counts,
        "today": [_lesson(pl) for pl in lessons.filter(date=today).order_by("period")],
        "upcoming": [_lesson(pl) for pl in lessons.filter(date__gt=today).order_by("date", "period")[:3]],
        "review": review,
        "last_verify": verify and {"id": verify.pk, "ok": verify.ok, "at": verify.finished_at,
                                   "summary": verify.summary},
    }


PREP_KEYS = ("week", "week_range", "folder", "section", "lessons", "message", "pages_unknown", "downloads", "files",
             "stale_years", "word_check", "same_as_previous", "platform_differs", "errors", "teacher_missing", "error")


def prep_overview(klass: PlatformClass, today: date) -> dict:
    """حزمة التحضير: أسابيع التدريس في الخطة (القادم أولًا للاختيار) وآخر حزمة بُنيت للصف."""
    weeks = list(klass.plan.weeks.filter(week_type="تدريس").order_by("week_no")
                 .values("week_no", "start_date", "end_date"))
    upcoming = next((w["week_no"] for w in weeks if w["start_date"] > today), weeks[-1]["week_no"] if weeks else None)
    last = klass.runs.filter(kind=SyncRun.Kind.PREP).first()
    return {
        "weeks": weeks, "next_week": upcoming,
        "last": last and {"id": last.pk, "ok": last.ok, "at": last.finished_at or last.started_at,
                          **{k: last.summary[k] for k in PREP_KEYS if k in last.summary}},
    }
