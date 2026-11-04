"""
الدورة الأسبوعية: التواريخ ثم الإسناد ثم النشر ثم التحقق، تلقائيًا مع تقرير بعدها (قرار المعلم).

الصمّامات، لأن الأتمتة تقرأ صفحات المنصة لا واجهة رسمية:
- شكل المنصة: الجلب يتوقف إن لم يجد دروسًا أو نقص عددها كثيرًا (SyncService.fetch).
- النافذة: يُعتمد آليًا ما يقع في الأيام القادمة فقط؛ الماضي وما عليه تنبيه يبقى لمراجعة المعلم.
- العدد غير المألوف: إن زاد المؤهَّل في مرحلة على الحد، لا يُعتمد منه شيء ويبقى للمراجعة.
- التحقق من منظور الطالب في النهاية دائمًا.
"""
from collections.abc import Callable
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db.models import QuerySet

from neo.models import AssignProposal, DateProposal, Job, PlatformClass, PublishProposal, SyncRun
from neo.services import live, pipeline, scorecard_service

APPLY_KINDS = (SyncRun.Kind.APPLY, SyncRun.Kind.ASSIGN_APPLY, SyncRun.Kind.PUBLISH_APPLY)
Report = dict  # {"classes": {اسم الصف: {المرحلة: {...}}}, "verify": {...}}


def config() -> dict:
    return {"enabled": True, "weekday": 3, "hour": 14, "catchup_hours": 66, "window_days": 14,
            "max_per_stage": 20, **getattr(settings, "NEO_WEEKLY", {})}


# ------------------------------------------------------------- الجدولة

def cycle_start(now: datetime) -> datetime:
    """أحدث موعد دورة (الخميس بعد الدوام افتراضًا) لا يتجاوز الآن."""
    c = config()
    start = now.replace(hour=c["hour"], minute=0, second=0, microsecond=0) \
        - timedelta(days=(now.weekday() - c["weekday"]) % 7)
    return start if start <= now else start - timedelta(days=7)


def next_run(now: datetime) -> datetime:
    return cycle_start(now) + timedelta(days=7)


def due_cycle(now: datetime) -> str | None:
    """
    الدورة المستحقة الآن، أو None. تُستدرك إن كان الجهاز مغلقًا وقت موعدها ما دامت في مهلة الاستدراك
    (حتى صباح الأحد افتراضًا)؛ بعدها لا فائدة منها. الدورة التي تمت أو تعمل لا تتكرر،
    والفاشلة تُعاد بعد ساعة (انتهاء الجلسة مثلًا، حتى يدخل المعلم).
    """
    c = config()
    start = cycle_start(now)
    if not c["enabled"] or now - start > timedelta(hours=c["catchup_hours"]):
        return None
    key = start.date().isoformat()
    jobs = Job.objects.filter(kind=Job.Kind.WEEKLY, params__cycle=key)
    if jobs.filter(status__in=[Job.Status.DONE, *Job.ACTIVE]).exists():
        return None
    if jobs.filter(finished_at__gte=now - timedelta(hours=1)).exists():
        return None
    return key


# ------------------------------------------------------------- الاعتماد الآلي

def _auto_approve(qs: QuerySet, eligible: QuerySet, stage: dict) -> int:
    """يعتمد المؤهَّل ما لم يتجاوز الحد؛ ويسجّل في التقرير ما بقي للمراجعة ولماذا."""
    pending = qs.filter(status=DateProposal.Status.PENDING)
    n = eligible.count()
    stage.update(proposals=pending.count(), eligible=n, held=pending.count() - n, approved=0)
    if n > config()["max_per_stage"]:
        stage.update(held=pending.count(), anomaly=f"{n} تغييرًا يتجاوز الحد {config()['max_per_stage']}؛ "
                                                   "لم يُعتمد شيء، راجعها يدويًا")
        live.emit("warn", f"اعتماد آلي موقوف: {stage['anomaly']}", node="approve")
        return 0
    stage["approved"] = eligible.update(status=DateProposal.Status.APPROVED)
    if stage["approved"] or stage["held"]:
        live.step(f"اعتماد آلي ضمن الصمّامات: {stage['approved']}، وبقي للمراجعة {stage['held']}", node="approve")
    return stage["approved"]


def _applied(stage: dict, runs: list[SyncRun]) -> list[SyncRun]:
    apply = next((r for r in runs if r.kind in APPLY_KINDS), None)
    if apply:
        stage.update(applied=apply.summary.get("applied", 0), failed=apply.summary.get("failed", 0), ok=apply.ok)
    return runs


def run(classes: list[PlatformClass], factory: pipeline.Factory, today: date, report: Report) -> list[SyncRun]:
    """يملأ report أثناء التنفيذ، فيبقى ما تم إن انقطعت الجلسة في منتصف الدورة."""
    horizon = today + timedelta(days=config()["window_days"])
    by_class = report.setdefault("classes", {k.name: {} for k in classes})
    report.update(today=today.isoformat(), horizon=horizon.isoformat())
    runs: list[SyncRun] = []

    def stage(k: PlatformClass, name: str) -> dict:
        return by_class[k.name].setdefault(name, {})

    # 1) التواريخ
    for plan in [r for r in pipeline.sync_plan(classes, factory, today) if r.kind == SyncRun.Kind.PLAN] \
            or []:
        runs.append(plan)
        s = stage(plan.klass, "dates")
        qs = plan.proposals.all()
        ok = qs.filter(status=DateProposal.Status.PENDING, flags="", proposed_date__range=(today, horizon))
        if _auto_approve(qs, ok, s):
            runs += _applied(s, pipeline.sync_apply(plan.pk, factory, today))

    # 2) الإسناد (يجلب التواريخ الجديدة أولًا)
    for plan in pipeline.assign_plan(classes, factory, today):
        runs.append(plan)
        s = stage(plan.klass, "assign")
        qs = plan.assign_proposals.all()
        ok = qs.filter(status=AssignProposal.Status.PENDING, flags="", lesson_date__range=(today, horizon))
        if _auto_approve(qs, ok, s):
            runs += _applied(s, pipeline.assign_apply(plan.pk, factory, today))

    # 3) النشر، وتطبيقه يتحقق من منظور الطالب
    verified = set()
    for plan in [r for r in pipeline.publish_plan(classes, factory) if r.kind == SyncRun.Kind.PUBLISH_PLAN]:
        runs.append(plan)
        s = stage(plan.klass, "publish")
        qs = plan.publish_proposals.all()
        if plan.ok and _auto_approve(qs, qs.filter(status=PublishProposal.Status.PENDING), s):
            runs += _applied(s, pipeline.publish_apply(plan.pk, factory, today))
            verified.add(plan.klass_id)
        elif not plan.ok:
            s.update(held=qs.count(), anomaly=plan.summary.get("points_error", "اقتراح النشر غير سليم"))

    # 4) التحقق لمن لم يُتحقق منه بعد النشر
    rest = [k for k in classes if k.pk not in verified]
    if rest:
        runs += pipeline.verify(rest, factory, today)
    for r in runs:
        if r.kind == SyncRun.Kind.VERIFY:
            by_class[r.klass.name]["verify"] = {"ok": r.ok, "missing_past": r.summary.get("missing_past", []),
                                                "missing_today": r.summary.get("missing_today", [])}
    report["attention"] = sum(
        bool(s.get("held") or s.get("anomaly") or s.get("failed") or s.get("ok") is False)
        for stages in by_class.values() for s in stages.values())
    live.stage("لقطة بطاقة الأداء", "scorecard")
    scorecard_service.snapshot(today)  # يظهر أثر الدورة على خط الأساس في بطاقة الأداء وتقرير SWOT
    report["snapshot"] = today.isoformat()
    return runs


def enqueue_due(now: datetime, enqueue: Callable[..., tuple[Job, bool]]) -> Job | None:
    key = due_cycle(now)
    return enqueue(Job.Kind.WEEKLY, {"cycle": key})[0] if key else None
