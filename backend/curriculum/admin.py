from django.contrib import admin
from django.db.models import Sum

from curriculum import models as m

admin.site.site_header = "أتمتة منصة قطر للتعليم"
admin.site.site_title = "أتمتة منصة قطر للتعليم"
admin.site.index_title = "إدارة الخطط الفصلية"


class UnitInline(admin.TabularInline):
    model = m.Unit
    extra = 0


class EntryInline(admin.TabularInline):
    model = m.ScheduleEntry
    extra = 0
    fields = ("seq", "unit", "lesson", "activity_type", "title", "periods")
    autocomplete_fields = ("lesson",)


class OutcomeInline(admin.StackedInline):
    model = m.LearningOutcome
    extra = 0


@admin.register(m.Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("__str__", "tracks", "platform_class", "total_periods")
    inlines = [UnitInline]

    @admin.display(description="مجموع الحصص")
    def total_periods(self, obj):
        return obj.entries.aggregate(s=Sum("periods"))["s"] or 0


@admin.register(m.Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ("week_no", "plan", "start_date", "end_date", "week_type", "periods")
    list_filter = ("plan", "week_type")
    date_hierarchy = "start_date"
    inlines = [EntryInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("plan").annotate(_periods=Sum("entries__periods"))

    @admin.display(description="الحصص", ordering="_periods")
    def periods(self, obj):
        return obj._periods or 0


@admin.register(m.ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    list_display = ("week", "seq", "plan", "unit", "activity_type", "title", "periods")
    list_filter = ("plan", "activity_type", "unit")
    search_fields = ("title", "lesson__code")
    list_select_related = ("week", "plan", "unit")


@admin.register(m.Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "plan", "unit", "in_schedule", "total_periods")
    list_filter = ("plan", "unit", "in_schedule")
    search_fields = ("code", "title")
    list_select_related = ("plan", "unit")


@admin.register(m.Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("__str__", "plan", "domain")
    list_filter = ("plan",)


@admin.register(m.OutcomeBlock)
class OutcomeBlockAdmin(admin.ModelAdmin):
    list_display = ("__str__", "plan", "week_from", "week_to")
    list_filter = ("plan", "unit")
    filter_horizontal = ("competencies", "values")
    inlines = [OutcomeInline]


@admin.register(m.LearningOutcome)
class LearningOutcomeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "block")
    list_filter = ("block__plan",)
    search_fields = ("text",)


@admin.register(m.CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "start_date", "end_date", "plan", "note")
    list_filter = ("event_type", "plan")


@admin.register(m.EnrichmentItem)
class EnrichmentItemAdmin(admin.ModelAdmin):
    list_display = ("lesson", "detail", "plan")
    list_filter = ("plan",)


@admin.register(m.Guideline)
class GuidelineAdmin(admin.ModelAdmin):
    list_display = ("seq", "title", "plan")
    list_filter = ("plan",)


@admin.register(m.TeachingStep)
class TeachingStepAdmin(admin.ModelAdmin):
    list_display = ("seq", "component", "procedure", "plan")


admin.site.register(m.Competency)
admin.site.register(m.CoreValue)
admin.site.register(m.SourceDocument)
