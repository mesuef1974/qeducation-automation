from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from neo.api import serializers as s
from neo.models import Job, PlatformClass, PlatformLesson, SyncRun
from neo.services import review_service, scorecard_service, weekly_service
from neo.services.job_service import JobService, session_state
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


class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    """الدروس: ?class=LMS_ID&hidden=1&dated=0"""

    serializer_class = s.LessonSerializer
    lookup_field = "lms_lesson_id"

    def get_queryset(self):
        qs = PlatformLesson.objects.filter(klass__active=True).select_related("klass")
        if (lms := _int_param(self.request, "class")) is not None:
            qs = qs.filter(klass__lms_id=lms)
        for flag, field in (("hidden", "hidden"), ("dated", "date__isnull")):
            raw = self.request.query_params.get(flag)
            if raw in ("0", "1"):
                qs = qs.filter(**{field: (raw == "1") != (flag == "dated")})
        return qs.order_by("klass", "position")


class RunViewSet(viewsets.ReadOnlyModelViewSet):
    """السجل: ?class=LMS_ID&kind=verify"""

    serializer_class = s.RunSerializer
    pagination_class = Page

    def get_queryset(self):
        qs = SyncRun.objects.select_related("klass")
        if (lms := _int_param(self.request, "class")) is not None:
            qs = qs.filter(klass__lms_id=lms)
        if kind := self.request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
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


class JobViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    المهام: GET /api/neo/jobs/ ، POST {"kind": "...", "params": {...}} ، POST /api/neo/jobs/{id}/cancel/
    الطلب المكرر لمهمة نشطة يعيدها (200) بدل إنشاء أخرى (201).
    """

    serializer_class = s.JobSerializer
    pagination_class = Page

    def get_queryset(self):
        qs = Job.objects.prefetch_related("runs__klass")
        if st := self.request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
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


@api_view(["GET"])
def weekly(request):
    """الدورة الأسبوعية: موعدها القادم وآخر دورة بتقريرها."""
    now = timezone.localtime()
    last = Job.objects.filter(kind=Job.Kind.WEEKLY).order_by("-created_at").first()
    return Response({"enabled": weekly_service.config()["enabled"], "next_at": weekly_service.next_run(now),
                     "due": weekly_service.due_cycle(now), "cycle": weekly_service.cycle_start(now).date(),
                     "last": s.JobSerializer(last).data if last else None})
