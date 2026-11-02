from dataclasses import asdict
from datetime import date

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from curriculum import models as m
from curriculum.api.serializers import CalendarEventSerializer, LessonSerializer, PlanSerializer
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
    """الخطط بالمستوى: /api/plans/10/ و /api/plans/12/"""

    serializer_class = PlanSerializer
    lookup_field = "grade_level"
    queryset = m.Plan.objects.prefetch_related("units")

    @action(detail=True)
    def lessons(self, request, grade_level=None):
        qs = m.Lesson.objects.filter(plan__grade_level=grade_level).select_related("unit")
        return Response(LessonSerializer(qs, many=True).data)

    @action(detail=True, url_path="current-week")
    def current_week(self, request, grade_level=None):
        snap = ScheduleService().week_for_date(int(grade_level), _date_param(request))
        if snap is None:
            raise NotFound("انتهى الفصل الدراسي")
        return Response(asdict(snap))

    @action(detail=True, url_path=r"weeks/(?P<week_no>\d+)")
    def week(self, request, grade_level=None, week_no=None):
        snap = ScheduleService().week_by_no(int(grade_level), int(week_no))
        if snap is None:
            raise NotFound()
        return Response(asdict(snap))

    @action(detail=True)
    def progress(self, request, grade_level=None):
        p = ScheduleService().progress(int(grade_level), _date_param(request))
        return Response({**asdict(p), "percent": p.percent})


class CalendarViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CalendarEventSerializer
    # الأحداث مشتركة بين الخطتين؛ تُعرض مرة واحدة
    queryset = m.CalendarEvent.objects.filter(plan__grade_level=10).order_by("start_date")
