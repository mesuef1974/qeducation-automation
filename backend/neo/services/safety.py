"""
صمّامات الكتابة على المنصة (docs/automation_criteria.md: الخطوات 1 و4 و5 والإيقاف الآلي). لا يلمس المنصة.

- الإيقاف الآلي: كتابة خاطئة واحدة (قراءة بعدية بقيمة غير المعتمدة ولا السابقة) أو تحققان فاشلان متتاليان من
  منظور الطالب يوقفان الدورة الأسبوعية وكل كتابة على المنصة حتى يعيد المعلم التفعيل. القراءة تستمر.
- صلاحية الاعتماد: تسقط بعد 48 ساعة، أو إن تغيّر الدرس على المنصة بعده (البصمة)، أو صارت مطابقته غير مؤكدة،
  فيعود الاقتراح للمراجعة بسببه.
- المطابقة: لا يُعتمد ولا يُكتب على درس مطابقته بالخطة غير مؤكدة (PlatformLesson.match_sure).
- الحداثة: لا كتابة على مزامنة أقدم من ساعة (FRESH_FOR؛ يطبّقها pipeline قبل كل تطبيق).
"""
import hashlib
from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from neo.models import AssignProposal, DateProposal, PlatformLesson, ProposalStatus, PublishProposal, SafetyState
from neo.services import live

APPROVAL_TTL = timedelta(hours=48)
FRESH_FOR = timedelta(hours=1)
VERIFY_FAILS_TO_HALT = 2


class WritesHalted(RuntimeError):
    """الكتابة على المنصة موقوفة بمفتاح الإيقاف الآلي حتى يعيد المعلم تفعيلها."""


# ------------------------------------------------------------- مفتاح الإيقاف

def state() -> SafetyState:
    return SafetyState.objects.get_or_create(pk=1)[0]


def halt(reason: str) -> SafetyState:
    """يوقف الكتابة كلها؛ السبب الأول يبقى حتى إعادة التفعيل."""
    s = state()
    if not s.halted:
        s.halted, s.reason, s.halted_at = True, reason[:1000], timezone.now()
        s.save(update_fields=["halted", "reason", "halted_at"])
    live.emit("error", f"أُوقفت الكتابة على المنصة: {reason}"[:500])
    return s


def resume() -> SafetyState:
    s = state()
    s.halted, s.reason, s.verify_failures, s.resumed_at = False, "", 0, timezone.now()
    s.save(update_fields=["halted", "reason", "verify_failures", "resumed_at"])
    return s


def require_writes_allowed() -> None:
    s = state()
    if s.halted:
        since = f" منذ {timezone.localtime(s.halted_at):%Y-%m-%d %H:%M}" if s.halted_at else ""
        raise WritesHalted(f"الكتابة على المنصة موقوفة{since}: {s.reason}. راجع السبب ثم أعد التفعيل من الواجهة.")


def record_verify(ok: bool) -> SafetyState:
    """جولة تحقق من منظور الطالب: النجاح يصفّر العدّاد، وفشلان متتاليان يوقفان الكتابة."""
    s = state()
    s.verify_failures = 0 if ok else s.verify_failures + 1
    s.save(update_fields=["verify_failures"])
    if s.verify_failures >= VERIFY_FAILS_TO_HALT:
        s = halt(f"فشل التحقق من منظور الطالب {s.verify_failures} مرات متتالية")
    return s


# ------------------------------------------------------------- الاعتماد وصلاحيته

def _related(model) -> list[str]:
    return ["assessment"] if model is AssignProposal else ["lesson"]


def lesson_of(p) -> PlatformLesson | None:
    return p.assessment.lesson if isinstance(p, AssignProposal) else p.lesson


def lesson_sure(p) -> bool:
    pl = lesson_of(p)
    return pl is not None and pl.match_sure


def unconfirmed_label(pl: PlatformLesson) -> str:
    """سطر التنبيه لدرس استُبعد لأن مطابقته غير مؤكدة."""
    return f"{pl.position}. {pl.title} ({pl.match_code or 'بلا مطابقة'}، {round((pl.match_score or 0) * 100)}%)"


def _fp(*parts) -> str:
    return hashlib.sha1("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()


def fingerprint(p) -> str:
    """ما يجب ألا يتغيّر على المنصة بين الاعتماد والتطبيق، لكل نوع اقتراح."""
    if isinstance(p, AssignProposal):
        a, pl = p.assessment, p.assessment.lesson
        return _fp(a.lms_assignment_id, a.title, a.lms_lesson_id, a.given, pl and pl.date)
    pl = p.lesson
    if isinstance(p, DateProposal):
        return _fp(pl.lms_lesson_id, pl.position, pl.title, pl.date, pl.period)
    if isinstance(p, PublishProposal):
        return _fp(pl.lms_lesson_id, pl.position, pl.title, pl.date, pl.hidden, pl.awards_points)
    return _fp(pl.lms_lesson_id, pl.position, pl.title)  # المحتوى: الدرس يُقرأ قبل كل إضافة


def mark_approved(qs: QuerySet) -> int:
    """يعتمد المنتظر في qs ويسجّل وقت الاعتماد وبصمة الدرس؛ ما مطابقة درسه غير مؤكدة لا يُعتمد."""
    now = timezone.now()
    items = [p for p in qs.filter(status=ProposalStatus.PENDING).select_related(*_related(qs.model)) if lesson_sure(p)]
    for p in items:
        p.status, p.approved_at, p.approved_fp, p.error = ProposalStatus.APPROVED, now, fingerprint(p), ""
    qs.model.objects.bulk_update(items, ["status", "approved_at", "approved_fp", "error"])
    return len(items)


def check_approvals(qs: QuerySet) -> list[str]:
    """
    قبل التطبيق، بعد جلب حديث: المعتمد منذ أكثر من 48 ساعة، أو تغيّر درسه على المنصة بعد اعتماده، أو صارت مطابقته
    غير مؤكدة، يعود للمراجعة بسببه. يعيد أسباب ما أُعيد.
    """
    now, back = timezone.now(), []
    for p in qs.filter(status=ProposalStatus.APPROVED).select_related(*_related(qs.model)):
        if not p.approved_at or now - p.approved_at > APPROVAL_TTL:
            p.error = "انتهت صلاحية الاعتماد (48 ساعة)؛ راجعه واعتمده من جديد"
        elif not lesson_sure(p):
            p.error = "مطابقة الدرس بالخطة غير مؤكدة؛ أكّدها ثم اعتمد من جديد"
        elif p.approved_fp != fingerprint(p):
            p.error = "تغيّر الدرس على المنصة بعد الاعتماد؛ راجعه واعتمده من جديد"
        else:
            continue
        p.status, p.approved_at, p.approved_fp = ProposalStatus.PENDING, None, ""
        back.append(p)
    qs.model.objects.bulk_update(back, ["status", "error", "approved_at", "approved_fp"])
    if back:
        live.emit("warn", f"عاد {len(back)} اعتمادًا إلى المراجعة: {back[0].error}")
    return [p.error for p in back]
