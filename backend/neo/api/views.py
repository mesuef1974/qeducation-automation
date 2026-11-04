from datetime import date, timedelta

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from django.utils._os import safe_join
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from neo.api import serializers as s
from neo.domain import assessment
from neo.models import (
    Job,
    PlatformClass,
    PlatformLesson,
    ProposalStatus,
    SyncRun,
    WorkerHeartbeat,
)
from neo.services import live, review_service, safety, scorecard_service, usage, weekly_service
from neo.services.job_service import JobService, session_state, worker_alive
from neo.services.pipeline import PROPOSALS, PipelineError


class Page(LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


def _int_param(request, name):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError({name: "رقم"}) from exc


class ClassViewSet(viewsets.ReadOnlyModelViewSet):
    """الصفوف المفعّلة مع ملخص «اليوم»: /api/neo/classes/ و /api/neo/classes/{lms_id}/"""

    serializer_class = s.ClassSerializer
    lookup_field = "lms_id"

    def get_queryset(self):
        return PlatformClass.objects.active()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        today = timezone.localdate()
        qs = self.get_queryset()
        if self.kwargs.get("lms_id"):
            qs = qs.filter(lms_id=self.kwargs["lms_id"])
        ctx["overviews"] = {k.pk: review_service.class_overview(k, today) for k in qs}
        return ctx

    @action(detail=True, methods=["post"], url_path="accept-shrink")
    def accept_shrink(self, request, lms_id=None):
        """الحذف المقصود (الخطوة 1): يؤكده المعلم مرة واحدة فتقبل المزامنة التالية نقص الدروس، ثم يعود الحارس."""
        klass = self.get_object()
        if not klass.shrink_pending:
            raise ValidationError("لا نقص بانتظار التأكيد لهذا الصف")
        klass.allow_shrink = True
        klass.save(update_fields=["allow_shrink"])
        return Response({"allow_shrink": True, "shrink_pending": klass.shrink_pending})


class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    """الدروس: ?class=LMS_ID&hidden=1&dated=0"""

    serializer_class = s.LessonSerializer
    lookup_field = "lms_lesson_id"

    def get_queryset(self):
        qs = PlatformLesson.objects.filter(klass__active=True).select_related("klass", "audit")
        if (lms := _int_param(self.request, "class")) is not None:
            qs = qs.filter(klass__lms_id=lms)
        for flag, field in (("hidden", "hidden"), ("dated", "date__isnull")):
            raw = self.request.query_params.get(flag)
            if raw in ("0", "1"):
                qs = qs.filter(**{field: (raw == "1") != (flag == "dated")})
        return qs.order_by("klass", "position")

    @action(detail=False, methods=["post"])
    def confirm(self, request):
        """
        تأكيد المطابقة الآلية مرة واحدة (الخطوة 1): POST /api/neo/lessons/confirm/ {"ids": [lms_lesson_id, ...]}
        الدرس المؤكد يدخل الاقتراح والكتابة ما بقيت مطابقته الآلية نفسها؛ إن تغيّرت عاد غير مؤكد.
        """
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            raise ValidationError({"ids": "قائمة معرّفات الدروس (lms_lesson_id)"})
        changed = 0
        for pl in PlatformLesson.objects.filter(lms_lesson_id__in=ids).exclude(match_code=""):
            if pl.confirmed_code != pl.match_code:
                pl.confirmed_code = pl.match_code
                pl.save(update_fields=["confirmed_code"])
                changed += 1
        return Response({"changed": changed})


class RunViewSet(viewsets.ReadOnlyModelViewSet):
    """السجل: ?class=LMS_ID&kind=verify[,apply]&id=RUN&plan_run=RUN (تطبيقات اقتراح بعينه)"""

    serializer_class = s.RunSerializer
    pagination_class = Page

    def get_queryset(self):
        qs = SyncRun.objects.select_related("klass")
        if (lms := _int_param(self.request, "class")) is not None:
            qs = qs.filter(klass__lms_id=lms)
        if kind := self.request.query_params.get("kind"):
            qs = qs.filter(kind__in=kind.split(","))
        if (pk := _int_param(self.request, "id")) is not None:
            qs = qs.filter(pk=pk)
        if (plan := _int_param(self.request, "plan_run")) is not None:
            qs = qs.filter(summary__plan_run=plan)  # عمليات التطبيق لاقتراح بعينه
        return qs


class ProposalViewSet(viewsets.ReadOnlyModelViewSet):
    """
    الاقتراحات بنوعها: /api/neo/proposals/{date|assign|publish}/?class=&run=&status=pending
    القرار: POST .../decide/ {"ids": [...], "decision": "approve|reject|reset"}
    """

    def _kind(self):
        kind = self.kwargs["kind"]
        if kind not in PROPOSALS:
            raise NotFound(f"نوع غير معروف: {kind}")
        return kind

    def get_serializer_class(self):
        return s.PROPOSAL_SERIALIZERS[self._kind()]

    def get_queryset(self):
        kind = self._kind()
        related = ["run__klass", "assessment"] if kind == "assign" else ["run__klass", "lesson"]
        qs = PROPOSALS[kind].objects.select_related(*related)
        if (lms := _int_param(self.request, "class")) is not None:
            qs = qs.filter(run__klass__lms_id=lms)
        if (run := _int_param(self.request, "run")) is not None:
            qs = qs.filter(run_id=run)
        if st := self.request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
        return qs

    @action(detail=False, methods=["post"])
    def decide(self, request, kind=None):
        body = s.DecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        changed = review_service.decide(self._kind(), body.validated_data["ids"], body.validated_data["decision"])
        return Response({"changed": changed})

    @action(detail=True, methods=["post"])
    def edit(self, request, kind=None, pk=None):
        """تعديل نص اقتراح المحتوى قبل اعتماده: POST .../content/{id}/edit/ {"text"|"name"|"html": ...}"""
        if self._kind() != "content":
            raise NotFound("التعديل لاقتراحات المحتوى فقط")
        prop = self.get_object()
        if prop.status != ProposalStatus.PENDING:
            raise ValidationError("يُعدَّل الاقتراح المنتظر فقط")
        body = s.PayloadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        unknown = set(body.validated_data) - set(prop.payload)
        if not body.validated_data or unknown:
            raise ValidationError({"payload": f"الحقول المقبولة: {sorted(prop.payload)}"})
        prop.payload = {**prop.payload, **body.validated_data}
        if prop.kind == "assessment" and "text" in body.validated_data:
            try:
                prop.payload["questions"] = [q.as_dict() for q in assessment.parse_text(prop.payload["text"])]
            except ValueError as exc:
                raise ValidationError({"text": str(exc)}) from exc
        prop.save(update_fields=["payload"])
        return Response(self.get_serializer(prop).data)

    @action(detail=True, methods=["get"])
    def image(self, request, kind=None, pk=None):
        """معاينة صورة البطاقة المولّدة: GET .../content/{id}/image/"""
        prop = self.get_object()
        if self._kind() != "content" or "file" not in prop.payload:
            raise NotFound("لا صورة لهذا الاقتراح")
        path = safe_join(str(settings.MEDIA_ROOT), prop.payload["file"])
        return FileResponse(open(path, "rb"), content_type="image/png")


class JobViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    المهام: GET /api/neo/jobs/[?status=&kind=] ، POST {"kind": "...", "params": {...}} ، POST /api/neo/jobs/{id}/cancel/
    الطلب المكرر لمهمة نشطة يعيدها (200) بدل إنشاء أخرى (201).
    """

    serializer_class = s.JobSerializer
    pagination_class = Page

    def get_queryset(self):
        qs = Job.objects.prefetch_related("runs__klass")
        if st := self.request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
        if kind := self.request.query_params.get("kind"):
            qs = qs.filter(kind__in=kind.split(","))
        return qs

    def create(self, request, *args, **kwargs):
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            job, created = JobService().enqueue(body.validated_data["kind"], body.validated_data.get("params"))
        except PipelineError as exc:
            raise ValidationError({"params": str(exc)}) from exc
        return Response(self.get_serializer(job).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        if not JobService().cancel(self.get_object()):
            raise ValidationError("لا تُلغى إلا المهمة المنتظرة")
        return Response(self.get_serializer(self.get_object()).data)


@ensure_csrf_cookie
@api_view(["GET"])
def session(request):
    """حالة جلسة المنصة والعامل: /api/neo/session/ (أول طلب للواجهة؛ يضبط ملف csrftoken لطلبات POST)"""
    return Response(session_state())


@api_view(["GET", "POST"])
def scorecard(request):
    """بطاقة الأداء: GET القيم الحالية مع خط الأساس، POST يحفظ لقطة اليوم (مرة لكل يوم)."""
    today = timezone.localdate()
    if request.method == "POST":
        _, created = scorecard_service.snapshot(today)
        return Response(status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    return Response({"current": scorecard_service.build(today), **scorecard_service.history()})


@api_view(["GET", "POST"])
def safety_state(request):
    """مفتاح الإيقاف الآلي: GET حالته؛ POST {"action": "resume"} يعيد تفعيل الكتابة بعد أن يراجع المعلم السبب."""
    if request.method == "POST":
        if request.data.get("action") != "resume":
            raise ValidationError({"action": "القيمة المقبولة: resume"})
        st = safety.resume()
    else:
        st = safety.state()
    return Response({"halted": st.halted, "reason": st.reason, "halted_at": st.halted_at,
                     "resumed_at": st.resumed_at, "verify_failures": st.verify_failures})


@api_view(["GET", "POST"])
def usage_summary(request):
    """
    تبويب «الاستهلاك» من قاعدة البيانات: ?days=7|30|90|all أو ?from=YYYY-MM-DD&to=، و?models=a,b، و?session=.
    العامل يستورد الجديد كل 10 دقائق؛ POST («تحديث فوري») يستورد بمهلة قصيرة ثم يعيد الملخص.
    """
    q = request.query_params
    today = timezone.localdate()

    def day(name):
        try:
            return date.fromisoformat(q[name]) if q.get(name) else None
        except ValueError as exc:
            raise ValidationError({name: "تاريخ YYYY-MM-DD"}) from exc

    since, until = day("from"), day("to")
    if not since and (d := q.get("days")):
        if d == "all":
            since = date(2000, 1, 1)
        elif d.isdigit() and int(d) > 0:
            since = today - timedelta(days=int(d) - 1)
        else:
            raise ValidationError({"days": "7 | 30 | 90 | all"})
    models = [m for m in (q.get("models") or "").split(",") if m] or None
    imported = usage.import_all() if request.method == "POST" else None
    return Response({**usage.build(today=today, since=since, until=until, models=models, session=q.get("session") or None),
                     "imported": imported})


@api_view(["POST"])
def weekly_read(request):
    """الملخص الثابت أعلى «اليوم» يبقى حتى يقرأه المعلم (الخطوة 9): POST يعلّم آخر دورة منتهية مقروءة."""
    last = Job.objects.filter(kind=Job.Kind.WEEKLY, finished_at__isnull=False).order_by("-created_at").first()
    if not last:
        raise NotFound("لم تُجرَ دورة بعد")
    last.report = {**last.report, "read_at": timezone.now().isoformat()}
    last.save(update_fields=["report"])
    return Response({"read_at": last.report["read_at"]})


@api_view(["GET"])
def weekly(request):
    """الدورة الأسبوعية: موعدها القادم وآخر دورة بتقريرها."""
    now = timezone.localtime()
    last = Job.objects.filter(kind=Job.Kind.WEEKLY).order_by("-created_at").first()
    cfg = weekly_service.config()
    return Response({"enabled": cfg["enabled"], "auto_approve": cfg["auto_approve"], "next_at": weekly_service.next_run(now),
                     "due": weekly_service.due_cycle(now), "cycle": weekly_service.cycle_start(now).date(),
                     "last": s.JobSerializer(last).data if last else None})


def _target(job: Job, names: dict[int, str]) -> str:
    p = job.params
    if p.get("class"):
        return f"{names.get(p['class'], p['class'])}" + (f" · الأسبوع {p['week']}" if p.get("week") else "")
    if p.get("classes"):
        return "، ".join(names.get(c, str(c)) for c in p["classes"])
    if p.get("run"):
        return f"الاقتراح #{p['run']}" + (f" · أول {p['limit']}" if p.get("limit") else "")
    return "كل الصفوف المفعّلة" if job.kind not in (Job.Kind.LOGIN,) else ""


def _job_lite(job: Job, names: dict[int, str]) -> dict:
    end = job.finished_at or timezone.now()
    return {"id": job.pk, "kind": job.kind, "kind_label": job.get_kind_display(), "target": _target(job, names),
            "status": job.status, "status_label": job.get_status_display(), "created_at": job.created_at,
            "started_at": job.started_at, "finished_at": job.finished_at, "error": job.error,
            "error_label": job.get_error_kind_display() if job.error_kind else "",
            "seconds": round((end - job.started_at).total_seconds()) if job.started_at else None}


@api_view(["GET"])
def live_feed(request):
    """
    تبويب «مباشر»: /api/neo/live/?since=SEQ[&job=ID]
    العامل ونبضه، والجلسة، والمهمة الجارية (أو آخر مهمة) بملخصها وأحداثها بعد since، والطابور، وآخر المهام.
    """
    since, job_id = _int_param(request, "since") or 0, _int_param(request, "job")
    names = dict(PlatformClass.objects.values_list("lms_id", "name"))
    running = Job.objects.filter(status=Job.Status.RUNNING).first()
    if job_id:
        focus = Job.objects.filter(pk=job_id).first()
    else:
        focus = running or Job.objects.filter(started_at__isnull=False).order_by("-started_at").first()
    beat = WorkerHeartbeat.objects.filter(pk=1).first()
    now = timezone.localtime()
    weekly_cfg = weekly_service.config()
    return Response({
        "now": timezone.now(),
        "worker": {"alive": worker_alive(), "pid": beat.pid if beat else None, "seen_at": beat.seen_at if beat else None},
        "session": session_state(),
        "job": focus and {**_job_lite(focus, names), "live": live.summary(focus.pk)},
        "events": live.read(focus.pk, since) if focus else [],
        "queue": [_job_lite(j, names) for j in Job.objects.filter(status=Job.Status.QUEUED).order_by("created_at")],
        "recent": [_job_lite(j, names) for j in Job.objects.filter(status__in=[Job.Status.DONE, Job.Status.FAILED])
                   .order_by("-finished_at")[:10]],
        "weekly": {"enabled": weekly_cfg["enabled"], "auto_approve": weekly_cfg["auto_approve"],
                   "next_at": weekly_service.next_run(now)},
    })
