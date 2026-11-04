"""
خطوات المراحل كما يشغّلها المعلم: أوامر neo_* وعامل المهام (neo_worker) يستدعيان هذه الدوال نفسها،
فلا يختلف ما يحدث من الطرفية عمّا يحدث من الواجهة. كل دالة تعيد عمليات SyncRun التي سجّلتها.
"""
from collections.abc import Callable
from datetime import date

from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn
from neo.models import AssignProposal, ContentProposal, DateProposal, PlatformClass, PublishProposal, SyncRun
from neo.services.assign_service import AssignService
from neo.services.audit_service import AuditService
from neo.services.content_service import ContentService
from neo.services import live, safety
from neo.services.prep_service import PackStopped, PrepService
from neo.services.publish_service import PublishService
from neo.services.sync_service import SyncService, active_classes
from neo.services.verify_service import VerifyService

Factory = Callable[[], NeoClient]


class PipelineError(ValueError):
    """طلب غير قابل للتنفيذ (عملية غير موجودة، لا اقتراحات معتمدة)؛ لا علاقة له بالمنصة."""


def _plan_run(run_id: int, kind: str) -> SyncRun:
    run = SyncRun.objects.select_related("klass").filter(pk=run_id, kind=kind).first()
    if not run:
        raise PipelineError(f"لا توجد عملية {SyncRun.Kind(kind).label} #{run_id}")
    return run


def _require_approved(qs) -> None:
    if not qs.filter(status=DateProposal.Status.APPROVED).exists():
        raise PipelineError("لا توجد اقتراحات معتمدة")


def _guard_apply(run: SyncRun, qs, factory: Factory) -> None:
    """
    صمّامات ما قبل كل كتابة على المنصة: الإيقاف الآلي، وحداثة المزامنة (لا كتابة على جلب أقدم من ساعة، فيُجلب
    الصف من جديد)، وصلاحية الاعتماد (48 ساعة، ودرس لم يتغيّر، ومطابقة مؤكدة)؛ ما سقط اعتماده يعود للمراجعة بسببه.
    """
    safety.require_writes_allowed()
    k = run.klass
    if not k.last_fetched_at or timezone.now() - k.last_fetched_at > safety.FRESH_FOR:
        live.stage(f"جلب حديث قبل الكتابة: آخر جلب أقدم من ساعة · {k}", "fetch")
        SyncService().fetch([k], factory)
    reasons = safety.check_approvals(qs)
    if reasons and not qs.filter(status=DateProposal.Status.APPROVED).exists():
        raise PipelineError(f"لا اعتماد صالح للتطبيق: {reasons[0]}")
    _require_approved(qs)


# ------------------------------------------------------------- المرحلة 1: التواريخ

def sync_plan(classes: list[PlatformClass], factory: Factory, today: date, fetch: bool = True) -> list[SyncRun]:
    svc = SyncService()
    runs = svc.fetch(classes, factory) if fetch else []
    live.stage("اقتراح التواريخ من الخطة", "plan")
    return runs + [svc.plan(k, today) for k in classes]


def sync_apply(run_id: int, factory: Factory, today: date, approve: str | None = None) -> list[SyncRun]:
    svc, run = SyncService(), _plan_run(run_id, SyncRun.Kind.PLAN)
    if approve:
        svc.approve(run_id, only_from=None if approve == "all" else today)
    _guard_apply(run, run.proposals.all(), factory)
    live.stage(f"كتابة التواريخ المعتمدة على المنصة · {run.klass}", "apply")
    return [svc.apply(run, factory)]


# ------------------------------------------------------------- المرحلة 2: الإسناد

def assign_plan(classes: list[PlatformClass], factory: Factory, today: date) -> list[SyncRun]:
    svc = AssignService()
    live.stage("جلب التقييمات من المنصة", "fetch")
    svc.fetch(classes, factory)
    live.stage("اقتراح الإسناد ومواعيده", "plan")
    return [svc.plan(k, today) for k in classes]


def assign_apply(run_id: int, factory: Factory, today: date, approve: str | None = None,
                 limit: int | None = None) -> list[SyncRun]:
    svc, run = AssignService(), _plan_run(run_id, SyncRun.Kind.ASSIGN_PLAN)
    if approve:
        svc.approve(run_id, None if approve == "all" else today)
    _guard_apply(run, run.assign_proposals.all(), factory)
    live.stage(f"ضبط مواعيد التقييمات وإسنادها · {run.klass}", "apply")
    return [svc.apply(run, factory, today, limit)]


# ------------------------------------------------------------- المرحلة 3: النشر

def publish_plan(classes: list[PlatformClass], factory: Factory) -> list[SyncRun]:
    svc = PublishService()
    fetched = SyncService().fetch(classes, factory)
    live.stage("قراءة رؤية الدروس ونقاطها", "fetch")
    games = svc.fetch(classes, factory)
    live.stage("اقتراح النشر", "plan")
    return fetched + [svc.plan(k, games[k.pk]) for k in classes]


def publish_apply(run_id: int, factory: Factory, today: date, approve: str | None = None,
                  limit: int | None = None) -> list[SyncRun]:
    """التطبيق ثم التحقق من منظور الطالب للصف نفسه."""
    svc, run = PublishService(), _plan_run(run_id, SyncRun.Kind.PUBLISH_PLAN)
    if approve:
        svc.approve(run_id)
    _guard_apply(run, run.publish_proposals.all(), factory)
    live.stage(f"إظهار الدروس ومنح النقاط · {run.klass}", "apply")
    return [svc.apply(run, factory, limit), *verify([run.klass], factory, today)]


# ------------------------------------------------------------- المرحلة 4: التحقق

def verify(classes: list[PlatformClass], factory: Factory, today: date) -> list[SyncRun]:
    fetched = SyncService().fetch(classes, factory)
    live.stage("التحقق من منظور الطالب", "verify")
    return fetched + VerifyService().run(classes, factory, today)


# ------------------------------------------------------------- المرحلة 6: جودة الدروس (قراءة فقط)

def audit(classes: list[PlatformClass], factory: Factory) -> list[SyncRun]:
    fetched = SyncService().fetch(classes, factory)
    live.stage("تدقيق جودة الدروس", "audit")
    return fetched + AuditService().run(classes, factory)


# ------------------------------------------------------------- المرحلة 8: المحتوى (إضافة باعتماد)

def content_plan(classes: list[PlatformClass], factory: Factory) -> list[SyncRun]:
    live.stage("قراءة الدروس الناقصة واقتراح المحتوى", "plan")
    return ContentService().plan(classes, factory)


def content_apply(run_id: int, factory: Factory, approve: str | None = None, lesson: int | None = None) -> list[SyncRun]:
    svc, run = ContentService(), _plan_run(run_id, SyncRun.Kind.CONTENT_PLAN)
    if approve:
        svc.approve(run_id, lesson)
    _guard_apply(run, run.content_proposals.all(), factory)
    live.stage(f"إضافة المحتوى المعتمد · {run.klass}", "apply")
    applied = svc.apply(run, factory, lesson)
    return [applied, *audit([run.klass], factory)]  # مزامنة ثم تدقيق: ما اكتمل يظهر فورًا


# ------------------------------------------------------------- المرحلة 9: حزمة التحضير الأسبوعية (قراءة فقط)

def prep_pack(lms_id: int, week: int, factory: Factory, policy: dict | None = None) -> list[SyncRun]:
    """جلب الدروس (تواريخ ومطابقة حديثة) ثم الحزمة: مجلد الأسبوع على سطح المكتب وصف الرسالة الأسبوعية."""
    classes = active_classes([lms_id])
    fetched = SyncService().fetch(classes, factory)
    try:
        return fetched + [PrepService(policy).run(classes[0], week, factory)]
    except PackStopped as exc:
        raise PipelineError(str(exc)) from exc


# ------------------------------------------------------------- الخطوة 0: الجلسة

def check_session(factory: Factory) -> dict:
    """الجلسة سارية؟ وإلا دخول صامت بالحساب الرسمي؛ وإن تعذّر يُرفع NotLoggedIn فيُنبَّه المعلم بزر الدخول."""
    live.stage("فحص جلسة المنصة", "platform")
    with factory() as client:
        try:
            client.get_html("/user_dashboard")
            return {"ok": True, "relogged": False}
        except NotLoggedIn:
            if client.login_silent():
                return {"ok": True, "relogged": True}
    raise NotLoggedIn("انتهت الجلسة وتعذّر الدخول الصامت بالحساب الرسمي: سجّل الدخول من نافذة الدخول")


PROPOSALS = {"date": DateProposal, "assign": AssignProposal, "publish": PublishProposal, "content": ContentProposal}
