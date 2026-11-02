from rest_framework import serializers

from curriculum import models as m


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Unit
        fields = ("unit_no", "title", "domain")


class PlanSerializer(serializers.ModelSerializer):
    units = UnitSerializer(many=True, read_only=True)

    class Meta:
        model = m.Plan
        fields = ("grade_level", "subject", "academic_year", "term_no", "tracks", "shift", "platform_class", "units")


class LessonSerializer(serializers.ModelSerializer):
    unit_no = serializers.IntegerField(source="unit.unit_no")

    class Meta:
        model = m.Lesson
        fields = ("code", "title", "unit_no", "in_schedule", "total_periods")


class CalendarEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.CalendarEvent
        fields = ("event_type", "title", "start_date", "end_date", "note")
