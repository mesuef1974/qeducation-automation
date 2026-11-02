"""
طابور المهام: الواجهة تطلب (enqueue)، والعامل يأخذ الأقدم (claim) وينفّذه (run).
الحالة في قاعدة البيانات فقط، فلا حاجة إلى Celery أو Redis لعامل محلي واحد.
"""
import json
from collections.abc import Callable
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from neo.infrastructure.client import BrowserBusy, NeoClient, NotLoggedIn, PlatformError
from neo.models import Job, SyncRun, WorkerHeartbeat
from neo.services import pipeline
from neo.services.sync_service import NoActiveClasses, active_classes

# headless → مصنع عملاء؛ الاختبارات تمرّر مصنعًا وهميًا
FactoryMaker = Callable[[bool], pipeline.Factory]
LOGIN_TIMEOUT = 600
HEARTBEAT_S = 5  # العامل يسجّل نبضه كل 5 ثوانٍ، حتى أثناء مهمة طويلة
ALIVE_S = 20     # بلا نبض طوال هذه المدة → العامل متوقف

# المعطيات المسموحة لكل نوع: classes = قائمة LMS IDs، run = عملية الاقتراح، approve، limit
PARAMS = {
    Job.Kind.LOGIN: set(),
    Job.Kind.SYNC_PLAN: {"classes"},
    Job.Kind.ASSIGN_PLAN: {"classes"},
    Job.Kind.PUBLISH_PLAN: {"classes"},
    Job.Kind.VERIFY: {"classes"},
    Job.Kind.SYNC_APPLY: {"run", "approve"},
    Job.Kind.ASSIGN_APPLY: {"run", "approve", "limit"},
    Job.Kind.PUBLISH_APPLY: {"run", "approve", "limit"},
}


def default_factory(headless: bool) -> pipeline.Factory:
    return lambda: NeoClient(headless=headless)


def job_key(kind: str, params: dict) -> str:
    return f"{kind}:{json.dumps(params, sort_keys=True)}"


def _execute(job: Job, make: FactoryMaker, today: date) -> list[SyncRun]:
    p, k = job.params, Job.Kind
    if job.kind == k.LOGIN:
        with make(False)() as client:
            client.login_interactive(LOGIN_TIMEOUT)
        return []
    factory = make(True)
    if job.kind in (k.SYNC_PLAN, k.ASSIGN_PLAN, k.PUBLISH_PLAN, k.VERIFY):
        classes = active_classes(p.get("classes"))
        return {
            k.SYNC_PLAN: lambda: pipeline.sync_plan(classes, factory, today),
            k.ASSIGN_PLAN: lambda: pipeline.assign_plan(classes, factory, today),
            k.PUBLISH_PLAN: lambda: pipeline.publish_plan(classes, factory),
            k.VERIFY: lambda: pipeline.verify(classes, factory, today),
        }[job.kind]()
    if job.kind == k.SYNC_APPLY:
        return pipeline.sync_apply(p["run"], factory, today, p.get("approve"))
    apply = pipeline.assign_apply if job.kind == k.ASSIGN_APPLY else pipeline.publish_apply
    return apply(p["run"], factory, today, p.get("approve"), p.get("limit"))


def _classify(exc: Exception) -> str:
    if isinstance(exc, NotLoggedIn):
        return Job.Error.SESSION
    if isinstance(exc, BrowserBusy):
        return Job.Error.BUSY
    if isinstance(exc, (pipeline.PipelineError, NoActiveClasses)):
        return Job.Error.INPUT
    if isinstance(exc, PlatformError):
        return Job.Error.PLATFORM
    return Job.Error.UNEXPECTED


class JobService:
    def enqueue(self, kind: str, params: dict | None = None) -> tuple[Job, bool]:
        """يعيد (المهمة، أُنشئت؟). المهمة المطابقة النشطة تُعاد بدل تكرارها."""
        params = {key: v for key, v in (params or {}).items() if v not in (None, [], "")}
        extra = set(params) - PARAMS[Job.Kind(kind)]
        if extra:
            raise pipeline.PipelineError(f"معطيات غير مقبولة لـ {kind}: {sorted(extra)}")
        key = job_key(kind, params)
        active = Job.objects.filter(key=key, status__in=Job.ACTIVE).first()
        if active:
            return active, False
        try:
            with transaction.atomic():
                return Job.objects.create(kind=kind, params=params, key=key), True
        except IntegrityError:  # سباق بين طلبين متطابقين
            return Job.objects.get(key=key, status__in=Job.ACTIVE), False

    def claim(self) -> Job | None:
        """يأخذ أقدم مهمة منتظرة ويعلّمها قيد التشغيل، ما لم تكن مهمة أخرى قيد التشغيل."""
        with transaction.atomic():
            if Job.objects.filter(status=Job.Status.RUNNING).exists():
                return None
            job = Job.objects.filter(status=Job.Status.QUEUED).order_by("created_at", "pk").first()
            if job is None:
                return None
            claimed = Job.objects.filter(pk=job.pk, status=Job.Status.QUEUED) \
                .update(status=Job.Status.RUNNING, started_at=timezone.now())
        return Job.objects.get(pk=job.pk) if claimed else None

    def run(self, job: Job, make: FactoryMaker = default_factory, today: date | None = None) -> Job:
        job.started_at = job.started_at or timezone.now()
        try:
            runs = _execute(job, make, today or timezone.localdate())
            job.status, job.error_kind, job.error = Job.Status.DONE, Job.Error.NONE, ""
        except Exception as exc:  # noqa: BLE001 - كل إخفاق يُسجَّل في المهمة ولا يوقف العامل
            job.status, job.error_kind, job.error = Job.Status.FAILED, _classify(exc), str(exc)[:1000]
            # المراحل تسجّل ما طُبّق قبل انقطاع الجلسة ثم ترفع الاستثناء؛ عامل واحد، فكل عملية منذ البداية لهذه المهمة
            runs = list(SyncRun.objects.filter(started_at__gte=job.started_at))
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "started_at", "error_kind", "error", "finished_at"])
        job.runs.set(runs)
        return job

    def recover(self) -> int:
        """عند بدء العامل: ما بقي «قيد التشغيل» توقف عامله فجأة."""
        return Job.objects.filter(status=Job.Status.RUNNING).update(
            status=Job.Status.FAILED, error_kind=Job.Error.UNEXPECTED, error="توقف العامل أثناء التنفيذ",
            finished_at=timezone.now())

    def cancel(self, job: Job) -> bool:
        """تُلغى المهمة المنتظرة فقط؛ الجارية لا تُقطع حتى لا تبقى المنصة في حالة وسطى."""
        return bool(Job.objects.filter(pk=job.pk, status=Job.Status.QUEUED).update(
            status=Job.Status.FAILED, error_kind=Job.Error.INPUT, error="أُلغيت قبل التشغيل",
            finished_at=timezone.now()))


def beat(pid: int) -> None:
    WorkerHeartbeat.objects.update_or_create(pk=1, defaults={"seen_at": timezone.now(), "pid": pid})


def stop_beat() -> None:
    WorkerHeartbeat.objects.filter(pk=1).delete()


def worker_alive() -> bool:
    return WorkerHeartbeat.objects.filter(pk=1, seen_at__gte=timezone.now() - timedelta(seconds=ALIVE_S)).exists()


def session_state() -> dict:
    """آخر ما نعرفه عن جلسة المنصة (من آخر مهمة وصلت المنصة فعلًا)، وحال العامل من نبضه."""
    # الطلب غير الصالح والمتصفح المشغول والتوقف المفاجئ لا تخبر بشيء عن الجلسة
    last = Job.objects.filter(Q(status=Job.Status.DONE) | Q(error_kind__in=[Job.Error.SESSION, Job.Error.PLATFORM])) \
        .order_by("-finished_at").first()
    alive = worker_alive()
    return {
        "expired": bool(last and last.error_kind == Job.Error.SESSION),
        "checked_at": last.finished_at if last else None,
        "worker_alive": alive,
        "worker_busy": alive and Job.objects.filter(status=Job.Status.RUNNING).exists(),
        "queued": Job.objects.filter(status=Job.Status.QUEUED).count(),
    }
