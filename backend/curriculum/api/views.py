from dataclasses import asdict
from datetime import date

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from curriculum import models as m
from curriculum.api.serializers import (
    CalendarEventSerializer,
    LessonSerializer,
    PlanSerializer,
)
from curriculum.services.schedule_service import ScheduleService


def _date_param(request) -> date:
    raw = request.query_params.get("date")
    if not raw:
        return timezone.localdate()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError({"date": "YYYY-MM-DD"}) from exc


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """
    الخطط بمعرّفها: /api/plans/{id}/
    التصفية: ?subject=&year=&term=&grade= (مثل /api/plans/?year=2026-2027&term=1&grade=12)
    """

    serializer_class = PlanSerializer
    FILTERS = {"subject": "subject", "year": "academic_year", "term": "term_no", "grade": "grade_level"}

    def get_queryset(self):
        qs = m.Plan.objects.prefetch_related("units")
        params = self.request.query_params
        return qs.filter(**{f: params[k] for k, f in self.FILTERS.items() if params.get(k)})

    @action(detail=True)
    def lessons(self, request, pk=None):
        qs = m.Lesson.objects.filter(plan=self.get_object()).select_related("unit")
        return Response(LessonSerializer(qs, many=True).data)

    @action(detail=True, url_path="current-week")
    def current_week(self, request, pk=None):
        snap = ScheduleService().week_for_date(self.get_object().pk, _date_param(request))
        if snap is None:
            raise NotFound("انتهى الفصل الدراسي")
        return Response(asdict(snap))

    @action(detail=True, url_path=r"weeks/(?P<week_no>\d+)")
    def week(self, request, pk=None, week_no=None):
        snap = ScheduleService().week_by_no(self.get_object().pk, int(week_no))
        if snap is None:
            raise NotFound()
        return Response(asdict(snap))

    @action(detail=True)
    def progress(self, request, pk=None):
        p = ScheduleService().progress(self.get_object().pk, _date_param(request))
        return Response({**asdict(p), "percent": p.percent})


class CalendarViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    أحداث التقويم: ?plan=ID لخطة واحدة، أو ?year=&term= لكل خططهما.
    الأحداث المشتركة بين الخطط (إجازات، اختبارات) تُعرض مرة واحدة.
    """

    serializer_class = CalendarEventSerializer
    pagination_class = None

    def get_queryset(self):
        params = self.request.query_params
        qs = m.CalendarEvent.objects.all()
        if params.get("plan"):
            qs = qs.filter(plan_id=params["plan"])
        if params.get("year"):
            qs = qs.filter(plan__academic_year=params["year"])
        if params.get("term"):
            qs = qs.filter(plan__term_no=params["term"])
        return (qs.values("event_type", "title", "start_date", "end_date", "note")
                .distinct().order_by("start_date", "title"))
