from rest_framework import serializers

from neo.domain.bidi import fix_ranges
from neo.domain.quality import ISSUES
from neo.domain.redact import scrub
from neo.models import (
    AssignProposal, ContentProposal, DateProposal, Job, LessonAudit, PlatformClass, PlatformLesson, PublishProposal,
    SyncRun,
)
from neo.services.job_service import PARAMS


class ClassSerializer(serializers.ModelSerializer):
    plan_title = serializers.SerializerMethodField()
    overview = serializers.SerializerMethodField()

    class Meta:
        model = PlatformClass
        fields = ["lms_id", "name", "active", "plan", "plan_title", "points_game", "points", "last_fetched_at",
                  "overview"]

    def get_plan_title(self, obj):
        # «الرياضيات - المستوى 10 - 2026-2027 ف1»: العام بعلامة LRM، وإلا ظهر «2027-2026»
        return fix_ranges(str(obj.plan)) if obj.plan else None

    def get_overview(self, obj):
        return self.context.get("overviews", {}).get(obj.pk)


class LessonAuditSerializer(serializers.ModelSerializer):
    issue_labels = serializers.SerializerMethodField()

    class Meta:
        model = LessonAudit
        fields = ["image_default", "sections", "has_outcomes", "issues", "issue_labels", "audited_at"]

    def get_issue_labels(self, a):
        return [ISSUES[i] for i in a.issues]


class LessonSerializer(serializers.ModelSerializer):
    lms_id = serializers.IntegerField(source="klass.lms_id", read_only=True)
    effective_code = serializers.CharField(read_only=True)
    audit = LessonAuditSerializer(read_only=True)

    class Meta:
        model = PlatformLesson
        fields = ["lms_lesson_id", "lms_id", "position", "title", "description", "date", "period", "hidden",
                  "awards_points", "match_code", "match_score", "override_code", "effective_code", "fetched_at", "audit"]


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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["error"] = scrub(data.get("error"))  # خطأ المنصة قد يحمل كوكيز الجلسة
        return data


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


class ContentProposalSerializer(_LessonProposalSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = ContentProposal
        fields = _ProposalSerializer.BASE + ["lesson", "kind", "kind_label", "payload"]


class PayloadSerializer(serializers.Serializer):
    """ما يجوز للمعلم تعديله قبل الاعتماد؛ الصورة تُولَّد ولا تُحرَّر."""
    text = serializers.CharField(required=False)
    name = serializers.CharField(required=False, max_length=100)
    html = serializers.CharField(required=False)


PROPOSAL_SERIALIZERS = {"date": DateProposalSerializer, "assign": AssignProposalSerializer, "content": ContentProposalSerializer,
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
                  "finished_at", "error_kind", "error_label", "error", "runs", "report"]
        read_only_fields = ["report", "status", "created_at", "started_at", "finished_at", "error_kind", "error"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["error"] = scrub(data.get("error"))  # خطأ المنصة قد يحمل كوكيز الجلسة
        return data

    def validate(self, attrs):
        params, allowed = attrs.get("params") or {}, PARAMS[attrs["kind"]]
        if not isinstance(params, dict) or set(params) - allowed:
            raise serializers.ValidationError({"params": f"المسموح: {sorted(allowed) or 'لا شيء'}"})
        if "run" in allowed and not isinstance(params.get("run"), int):
            raise serializers.ValidationError({"params": "run مطلوب (رقم عملية الاقتراح)"})
        if params.get("approve") not in (None, "all", "future"):
            raise serializers.ValidationError({"params": "approve: all | future"})
        for key in ("limit", "lesson"):
            if params.get(key) is not None and (not isinstance(params[key], int) or params[key] < 1):
                raise serializers.ValidationError({"params": f"{key} عدد موجب"})
        if attrs["kind"] == Job.Kind.PREP_PACK:
            for key in ("class", "week"):
                if not isinstance(params.get(key), int) or params[key] < 1:
                    raise serializers.ValidationError({"params": f"{key} مطلوب (رقم موجب)"})
        classes = params.get("classes")
        if classes is not None and (not isinstance(classes, list) or not all(isinstance(c, int) for c in classes)):
            raise serializers.ValidationError({"params": "classes قائمة LMS IDs"})
        return attrs
