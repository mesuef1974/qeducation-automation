"""
خطوات المراحل كما يشغّلها المعلم: أوامر neo_* وعامل المهام (neo_worker) يستدعيان هذه الدوال نفسها،
فلا يختلف ما يحدث من الطرفية عمّا يحدث من الواجهة. كل دالة تعيد عمليات SyncRun التي سجّلتها.
"""
from collections.abc import Callable
from datetime import date

from neo.infrastructure.client import NeoClient
from neo.models import AssignProposal, ContentProposal, DateProposal, PlatformClass, PublishProposal, SyncRun
from neo.services.assign_service import AssignService
from neo.services.audit_service import AuditService
from neo.services.content_service import ContentService
from neo.services import live
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


# ------------------------------------------------------------- المرحلة 1: التواريخ

def sync_plan(classes: list[PlatformClass], factory: Factory, today: date, fetch: bool = True) -> list[SyncRun]:
    svc = SyncService()
    runs = svc.fetch(classes, factory) if fetch else []
    live.stage("اقتراح التواريخ من الخطة")
    return runs + [svc.plan(k, today) for k in classes]


def sync_apply(run_id: int, factory: Factory, today: date, approve: str | None = None) -> list[SyncRun]:
    svc, run = SyncService(), _plan_run(run_id, SyncRun.Kind.PLAN)
    if approve:
        svc.approve(run_id, only_from=None if approve == "all" else today)
    _require_approved(run.proposals)
    live.stage(f"كتابة التواريخ المعتمدة على المنصة · {run.klass}")
    return [svc.apply(run, factory)]


# ------------------------------------------------------------- المرحلة 2: الإسناد

def assign_plan(classes: list[PlatformClass], factory: Factory, today: date) -> list[SyncRun]:
    svc = AssignService()
    live.stage("جلب التقييمات من المنصة")
    svc.fetch(classes, factory)
    live.stage("اقتراح الإسناد ومواعيده")
    return [svc.plan(k, today) for k in classes]


def assign_apply(run_id: int, factory: Factory, today: date, approve: str | None = None,
                 limit: int | None = None) -> list[SyncRun]:
    svc, run = AssignService(), _plan_run(run_id, SyncRun.Kind.ASSIGN_PLAN)
    if approve:
        svc.approve(run_id, None if approve == "all" else today)
    _require_approved(run.assign_proposals.all())
    live.stage(f"ضبط مواعيد التقييمات وإسنادها · {run.klass}")
    return [svc.apply(run, factory, today, limit)]


# ------------------------------------------------------------- المرحلة 3: النشر

def publish_plan(classes: list[PlatformClass], factory: Factory) -> list[SyncRun]:
    svc = PublishService()
    fetched = SyncService().fetch(classes, factory)
    live.stage("قراءة رؤية الدروس ونقاطها")
    games = svc.fetch(classes, factory)
    live.stage("اقتراح النشر")
    return fetched + [svc.plan(k, games[k.pk]) for k in classes]


def publish_apply(run_id: int, factory: Factory, today: date, approve: str | None = None,
                  limit: int | None = None) -> list[SyncRun]:
    """التطبيق ثم التحقق من منظور الطالب للصف نفسه."""
    svc, run = PublishService(), _plan_run(run_id, SyncRun.Kind.PUBLISH_PLAN)
    if approve:
        svc.approve(run_id)
    _require_approved(run.publish_proposals.all())
    live.stage(f"إظهار الدروس ومنح النقاط · {run.klass}")
    return [svc.apply(run, factory, limit), *verify([run.klass], factory, today)]


# ------------------------------------------------------------- المرحلة 4: التحقق

def verify(classes: list[PlatformClass], factory: Factory, today: date) -> list[SyncRun]:
    fetched = SyncService().fetch(classes, factory)
    live.stage("التحقق من منظور الطالب")
    return fetched + VerifyService().run(classes, factory, today)


# ------------------------------------------------------------- المرحلة 6: جودة الدروس (قراءة فقط)

def audit(classes: list[PlatformClass], factory: Factory) -> list[SyncRun]:
    fetched = SyncService().fetch(classes, factory)
    live.stage("تدقيق جودة الدروس")
    return fetched + AuditService().run(classes, factory)


# ------------------------------------------------------------- المرحلة 8: المحتوى (إضافة باعتماد)

def content_plan(classes: list[PlatformClass], factory: Factory) -> list[SyncRun]:
    live.stage("قراءة الدروس الناقصة واقتراح المحتوى")
    return ContentService().plan(classes, factory)


def content_apply(run_id: int, factory: Factory, approve: str | None = None, lesson: int | None = None) -> list[SyncRun]:
    svc, run = ContentService(), _plan_run(run_id, SyncRun.Kind.CONTENT_PLAN)
    if approve:
        svc.approve(run_id, lesson)
    _require_approved(run.content_proposals.all())
    live.stage(f"إضافة المحتوى المعتمد · {run.klass}")
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


PROPOSALS = {"date": DateProposal, "assign": AssignProposal, "publish": PublishProposal, "content": ContentProposal}
