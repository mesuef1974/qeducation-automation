from rest_framework import serializers

from neo.models import AssignProposal, DateProposal, Job, PlatformClass, PlatformLesson, PublishProposal, SyncRun
from neo.services.job_service import PARAMS


class ClassSerializer(serializers.ModelSerializer):
    plan_title = serializers.CharField(source="plan.__str__", read_only=True)
    overview = serializers.SerializerMethodField()

    class Meta:
        model = PlatformClass
        fields = ["lms_id", "name", "active", "plan", "plan_title", "points_game", "points", "last_fetched_at",
                  "overview"]

    def get_overview(self, obj):
        return self.context.get("overviews", {}).get(obj.pk)


class LessonSerializer(serializers.ModelSerializer):
    lms_id = serializers.IntegerField(source="klass.lms_id", read_only=True)
    effective_code = serializers.CharField(read_only=True)

    class Meta:
        model = PlatformLesson
        fields = ["lms_lesson_id", "lms_id", "position", "title", "description", "date", "period", "hidden",
                  "awards_points", "match_code", "match_score", "override_code", "effective_code", "fetched_at"]


class RunSerializer(serializers.ModelSerializer):
    lms_id = serializers.IntegerField(source="klass.lms_id", read_only=True)
    class_name = serializers.CharField(source="klass.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = SyncRun
        fields = ["id", "lms_id", "class_name", "kind", "kind_label", "started_at", "finished_at", "ok", "summary"]


class _ProposalSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    lms_id = serializers.IntegerField(source="run.klass.lms_id", read_only=True)

    BASE = ["id", "run", "lms_id", "status", "status_label", "error", "applied_at"]


class _LessonProposalSerializer(_ProposalSerializer):
    lesson = serializers.SerializerMethodField()

    def get_lesson(self, obj):
        pl = obj.lesson
        return {"id": pl.lms_lesson_id, "position": pl.position, "title": pl.title, "date": pl.date,
                "period": pl.period}


class DateProposalSerializer(_LessonProposalSerializer):
    class Meta:
        model = DateProposal
        fields = _ProposalSerializer.BASE + ["lesson", "proposed_date", "proposed_period", "plan_week_no", "flags"]


class PublishProposalSerializer(_LessonProposalSerializer):
    class Meta:
        model = PublishProposal
        fields = _ProposalSerializer.BASE + ["lesson", "show", "add_points"]


class AssignProposalSerializer(_ProposalSerializer):
    assessment = serializers.SerializerMethodField()

    class Meta:
        model = AssignProposal
        fields = _ProposalSerializer.BASE + ["assessment", "lesson_date", "begin_at", "end_at", "allow_late", "flags"]

    def get_assessment(self, obj):
        a = obj.assessment
        return {"id": a.lms_assignment_id, "title": a.title, "lesson_id": a.lms_lesson_id, "given": a.given}


PROPOSAL_SERIALIZERS = {"date": DateProposalSerializer, "assign": AssignProposalSerializer,
                        "publish": PublishProposalSerializer}


class DecisionSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=500)
    decision = serializers.ChoiceField(choices=["approve", "reject", "reset"])


class JobSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    error_label = serializers.CharField(source="get_error_kind_display", read_only=True)
    runs = RunSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = ["id", "kind", "kind_label", "params", "status", "status_label", "created_at", "started_at",
                  "finished_at", "error_kind", "error_label", "error", "runs"]
        read_only_fields = ["status", "created_at", "started_at", "finished_at", "error_kind", "error"]

    def validate(self, attrs):
        params, allowed = attrs.get("params") or {}, PARAMS[attrs["kind"]]
        if not isinstance(params, dict) or set(params) - allowed:
            raise serializers.ValidationError({"params": f"المسموح: {sorted(allowed) or 'لا شيء'}"})
        if "run" in allowed and not isinstance(params.get("run"), int):
            raise serializers.ValidationError({"params": "run مطلوب (رقم عملية الاقتراح)"})
        if params.get("approve") not in (None, "all", "future"):
            raise serializers.ValidationError({"params": "approve: all | future"})
        if params.get("limit") is not None and (not isinstance(params["limit"], int) or params["limit"] < 1):
            raise serializers.ValidationError({"params": "limit عدد موجب"})
        classes = params.get("classes")
        if classes is not None and (not isinstance(classes, list) or not all(isinstance(c, int) for c in classes)):
            raise serializers.ValidationError({"params": "classes قائمة LMS IDs"})
        return attrs
