"""
الدورة الأسبوعية (الخطوة 9): الاثنين 7:00، التواريخ ثم الإسناد ثم النشر ثم التحقق ثم حزمتا التحضير والرسالة للأسبوع
القادم ثم لقطة بطاقة الأداء، مع تقرير وتنبيه ويندوز بعدها.

الصمّامات، لأن الأتمتة تقرأ صفحات المنصة لا واجهة رسمية:
- شكل المنصة: الجلب يتوقف إن لم يجد دروسًا أو نقص عددها كثيرًا (SyncService.fetch).
- النافذة: يُعتمد آليًا ما يقع في الأيام القادمة فقط؛ الماضي وما عليه تنبيه يبقى لمراجعة المعلم.
- الحد: إن زاد المؤهَّل في مرحلة على عدد حصص الصف في النافذة، لا يُعتمد منه شيء ويبقى للمراجعة.
- الاعتماد الآلي للروتيني السليم فقط: بلا تنبيه، ومطابقة مؤكدة (الاقتراح يستبعد غيرها)، وضمن نافذة الأيام القادمة؛
  ويُسجَّل وقته وبصمة الدرس فيسقط بعد 48 ساعة أو إن تغيّر الدرس (safety).
- مفتاح الإيقاف الآلي: الدورة لا تستحق ولا تعمل والكتابة موقوفة.
- للمراجعة فقط (auto_approve=False): لا يُعتمد شيء آليًا، وكل المعلّق يبقى لقرار المعلم، فلا يُكتب شيء.
- التحقق من منظور الطالب في النهاية دائمًا.
"""
from collections.abc import Callable
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db.models import QuerySet

from neo.models import AssignProposal, DateProposal, Job, PlatformClass, PublishProposal, SyncRun
from neo.infrastructure.client import PlatformError
from neo.services import alerts, live, pipeline, safety, scorecard_service
from neo.services.scheduling import WeekSpan, build_slots

APPLY_KINDS = (SyncRun.Kind.APPLY, SyncRun.Kind.ASSIGN_APPLY, SyncRun.Kind.PUBLISH_APPLY)
Report = dict  # {"classes": {اسم الصف: {المرحلة: {...}}}, "verify": {...}}


LATE = timedelta(minutes=15)  # بعدها تُعدّ الدورة متأخرة فيُنبَّه المعلم
SESSION_HOUR = 6              # فحص الجلسة كل صباح قبل أي مهمة مجدولة (الدورة 7:00)


def config() -> dict:
    """since: أول يوم للجدول الحالي؛ الدورات قبله لا تُستدرك (تغيّر الموعد من الخميس إلى الاثنين)."""
    return {"enabled": True, "weekday": 0, "hour": 7, "catchup_hours": 7 * 24 - 1, "window_days": 14,
            "auto_approve": True, "since": "", **getattr(settings, "NEO_WEEKLY", {})}


# ------------------------------------------------------------- الجدولة

def cycle_start(now: datetime) -> datetime:
    """أحدث موعد دورة (الاثنين 7:00 افتراضًا) لا يتجاوز الآن."""
    c = config()
    start = now.replace(hour=c["hour"], minute=0, second=0, microsecond=0) \
        - timedelta(days=(now.weekday() - c["weekday"]) % 7)
    return start if start <= now else start - timedelta(days=7)


def next_run(now: datetime) -> datetime:
    return cycle_start(now) + timedelta(days=7)


def due_cycle(now: datetime) -> str | None:
    """
    الدورة المستحقة الآن، أو None. تُستدرك إن كان الجهاز مطفأً وقت موعدها، مرة واحدة في أي وقت قبل الدورة التالية
    (قرار المعلم). الدورة التي تمت أو تعمل لا تتكرر، والفاشلة تُعاد بعد ساعة، أو فور الدخول إن فشلت لانتهاء الجلسة
    (الخطوة 0: الدورة تنتظر ثم تكمل وحدها بعد الدخول). مفتاح الإيقاف الآلي يوقفها.
    """
    c = config()
    start = cycle_start(now)
    key = start.date().isoformat()
    if not c["enabled"] or safety.state().halted or now - start > timedelta(hours=c["catchup_hours"]):
        return None
    if c["since"] and key < c["since"]:
        return None
    jobs = Job.objects.filter(kind=Job.Kind.WEEKLY, params__cycle=key)
    if jobs.filter(status__in=[Job.Status.DONE, *Job.ACTIVE]).exists():
        return None
    recent = jobs.filter(finished_at__gte=now - timedelta(hours=1)).order_by("-finished_at").first()
    if recent and not (recent.error_kind == Job.Error.SESSION and _relogged_after(recent.finished_at)):
        return None
    return key


def _relogged_after(t: datetime) -> bool:
    return Job.objects.filter(kind__in=[Job.Kind.LOGIN, Job.Kind.SESSION], status=Job.Status.DONE,
                              finished_at__gt=t).exists()


def session_check_due(now: datetime, on_start: bool = False) -> bool:
    """فحص الجلسة (الخطوة 0): عند بدء العامل (ما لم يُفحص قبل نصف ساعة)، وكل صباح من 6:00 مرة واحدة."""
    jobs = Job.objects.filter(kind=Job.Kind.SESSION)
    if on_start:
        return not jobs.filter(created_at__gte=now - timedelta(minutes=30)).exists()
    since = now.replace(hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    return now >= since and not jobs.filter(created_at__gte=since).exists()


def periods_in_window(klass: PlatformClass, start: date, end: date) -> int:
    """الحد (الخطوة 9): عدد حصص الصف في النافذة، من جدوله وأسابيع التدريس في خطته."""
    weeks = [WeekSpan(w.week_no, w.start_date, w.week_type == "تدريس") for w in klass.plan.weeks.order_by("week_no")]
    slots = build_slots(weeks, list(klass.slots.values_list("weekday", "period")))
    return sum(1 for s in slots if start <= s.date <= end)


def next_teaching_week(klass: PlatformClass, today: date) -> int | None:
    week = klass.plan.weeks.filter(week_type="تدريس", start_date__gt=today).order_by("week_no").first()
    return week.week_no if week else None


# ------------------------------------------------------------- الاعتماد الآلي

def _auto_approve(qs: QuerySet, eligible: QuerySet, stage: dict, limit: int) -> int:
    """
    يعتمد المؤهَّل ما لم يتجاوز الحد (عدد حصص الصف في النافذة) أو كان الاعتماد الآلي معطّلًا؛ ويسجّل في التقرير
    ما بقي للمراجعة ولماذا.
    """
    pending = qs.filter(status=DateProposal.Status.PENDING)
    n = eligible.count()
    stage.update(proposals=pending.count(), eligible=n, held=pending.count() - n, approved=0, limit=limit)
    if not config()["auto_approve"]:
        stage.update(held=pending.count(), review_only=True)
        if stage["held"]:
            live.step(f"للمراجعة فقط: {stage['held']} اقتراحًا بانتظار اعتمادك، ولم يُكتب شيء", node="approve")
        return 0
    if n > limit:
        stage.update(held=pending.count(), anomaly=f"{n} تغييرًا يتجاوز عدد حصص الصف في النافذة ({limit})؛ "
                                                   "لم يُعتمد شيء، راجعها يدويًا")
        live.emit("warn", f"اعتماد آلي موقوف: {stage['anomaly']}", node="approve")
        return 0
    stage["approved"] = safety.mark_approved(eligible)
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
    safety.require_writes_allowed()  # الإيقاف الآلي يوقف الدورة كلها حتى يعيد المعلم التفعيل
    horizon = today + timedelta(days=config()["window_days"])
    limits = {k.pk: periods_in_window(k, today, horizon) for k in classes}
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
        if _auto_approve(qs, ok, s, limits[plan.klass_id]):
            runs += _applied(s, pipeline.sync_apply(plan.pk, factory, today))

    # 2) الإسناد (يجلب التواريخ الجديدة أولًا)
    for plan in pipeline.assign_plan(classes, factory, today):
        runs.append(plan)
        s = stage(plan.klass, "assign")
        qs = plan.assign_proposals.all()
        ok = qs.filter(status=AssignProposal.Status.PENDING, flags="", lesson_date__range=(today, horizon))
        if _auto_approve(qs, ok, s, limits[plan.klass_id]):
            runs += _applied(s, pipeline.assign_apply(plan.pk, factory, today))

    # 3) النشر، وتطبيقه يتحقق من منظور الطالب
    verified = set()
    for plan in [r for r in pipeline.publish_plan(classes, factory) if r.kind == SyncRun.Kind.PUBLISH_PLAN]:
        runs.append(plan)
        s = stage(plan.klass, "publish")
        qs = plan.publish_proposals.all()
        ok = qs.filter(status=PublishProposal.Status.PENDING, lesson__date__range=(today, horizon))
        if plan.ok and _auto_approve(qs, ok, s, limits[plan.klass_id]):
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
    # 5) حزمتا التحضير للأسبوع القادم والرسالة (قراءة فقط، إلى سطح المكتب)
    for k in classes:
        runs += _prep(k, factory, today, stage(k, "prep"))
    report["attention"] = sum(
        bool(s.get("held") or s.get("anomaly") or s.get("failed") or s.get("ok") is False)
        for stages in by_class.values() for s in stages.values())
    live.stage("لقطة بطاقة الأداء", "scorecard")
    scorecard_service.snapshot(today)  # يظهر أثر الدورة على خط الأساس في بطاقة الأداء وتقرير SWOT
    report["snapshot"] = today.isoformat()
    return runs


def _prep(klass: PlatformClass, factory: pipeline.Factory, today: date, s: dict) -> list[SyncRun]:
    """حزمة الأسبوع القادم للصف؛ تعذّرها يُسجَّل في التقرير ولا يوقف الدورة (انتهاء الجلسة وحده يوقفها)."""
    week = next_teaching_week(klass, today)
    if week is None:
        s.update(ok=False, error="لا أسبوع تدريس قادم في الخطة")
        return []
    live.stage(f"حزمة التحضير للأسبوع {week} · {klass.name}", "prep")
    try:
        runs = pipeline.prep_pack(klass.lms_id, week, factory)
    except (pipeline.PipelineError, PlatformError) as exc:
        s.update(week=week, ok=False, error=str(exc)[:300])
        return []
    pack = next((r for r in runs if r.kind == SyncRun.Kind.PREP), None)
    s.update(week=week, ok=bool(pack and pack.ok), folder=pack.summary.get("folder", "") if pack else "")
    return runs


def enqueue_due(now: datetime, enqueue: Callable[..., tuple[Job, bool]]) -> Job | None:
    key = due_cycle(now)
    if not key:
        return None
    job, created = enqueue(Job.Kind.WEEKLY, {"cycle": key})
    if created and now - cycle_start(now) > LATE:  # المهمة الفائتة تُستدرك مع تنبيه بالتأخير
        alerts.late_cycle(cycle_start(now))
    return job
