import json

from django.contrib import admin, messages
from django.utils.html import format_html

from neo.models import (
    AssignProposal,
    DateProposal,
    PlatformAssessment,
    PlatformClass,
    PlatformLesson,
    ProposalStatus,
    SyncRun,
    TimetableSlot,
)


class SlotInline(admin.TabularInline):
    model = TimetableSlot
    extra = 0


@admin.register(PlatformClass)
class PlatformClassAdmin(admin.ModelAdmin):
    list_display = ("name", "lms_id", "plan", "active", "last_fetched_at", "lessons_count")
    list_editable = ("active",)
    list_filter = ("active", "plan__academic_year", "plan__term_no", "plan__subject")
    list_select_related = ("plan",)
    readonly_fields = ("last_fetched_at",)
    inlines = [SlotInline]

    @admin.display(description="الدروس")
    def lessons_count(self, obj):
        return obj.lessons.count()


@admin.register(PlatformLesson)
class PlatformLessonAdmin(admin.ModelAdmin):
    list_display = ("position", "title", "klass", "date", "period", "match_code", "match_score", "override_code")
    list_display_links = ("title",)
    list_editable = ("override_code",)
    list_filter = ("klass", ("date", admin.EmptyFieldListFilter), "match_code")
    search_fields = ("title", "match_code", "override_code")
    readonly_fields = ("lms_lesson_id", "position", "title", "description", "date", "period",
                       "match_code", "match_score", "fetched_at", "klass")


class ProposalInline(admin.TabularInline):
    model = DateProposal
    extra = 0
    fields = ("lesson", "proposed_date", "proposed_period", "plan_week_no", "flags", "status", "error")
    readonly_fields = fields
    can_delete = False


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "klass", "started_at", "ok", "proposals_count")
    list_filter = ("kind", "klass", "ok")
    readonly_fields = ("klass", "kind", "started_at", "finished_at", "ok", "summary_pretty")
    exclude = ("summary",)
    inlines = [ProposalInline]

    @admin.display(description="الاقتراحات")
    def proposals_count(self, obj):
        return obj.proposals.count() or "-"

    @admin.display(description="الملخص")
    def summary_pretty(self, obj):
        return format_html('<pre dir="rtl" style="white-space:pre-wrap">{}</pre>',
                           json.dumps(obj.summary, ensure_ascii=False, indent=2))


class ReviewActionsMixin:
    actions = ["approve", "reject", "reset"]

    @admin.display(description="الصف")
    def klass(self, obj):
        return obj.run.klass

    def _transition(self, request, qs, to, allowed):
        n = qs.filter(status__in=allowed).update(status=to)
        self.message_user(request, f"تم تحديث {n} اقتراح.", messages.SUCCESS)

    @admin.action(description="اعتماد المحدد للتطبيق")
    def approve(self, request, qs):
        self._transition(request, qs, ProposalStatus.APPROVED, [ProposalStatus.PENDING])

    @admin.action(description="رفض المحدد")
    def reject(self, request, qs):
        self._transition(request, qs, ProposalStatus.REJECTED, [ProposalStatus.PENDING, ProposalStatus.APPROVED])

    @admin.action(description="إعادة إلى المراجعة")
    def reset(self, request, qs):
        self._transition(request, qs, ProposalStatus.PENDING, [ProposalStatus.APPROVED, ProposalStatus.REJECTED])


@admin.register(DateProposal)
class DateProposalAdmin(ReviewActionsMixin, admin.ModelAdmin):
    list_display = ("lesson", "klass", "proposed_date", "proposed_period", "plan_week_no", "flags", "status", "run")
    list_filter = ("status", "run__klass", "run", "flags")
    list_select_related = ("lesson", "run__klass")
    readonly_fields = ("run", "lesson", "proposed_date", "proposed_period", "plan_week_no", "flags",
                       "status", "error", "applied_at")


@admin.register(PlatformAssessment)
class PlatformAssessmentAdmin(admin.ModelAdmin):
    list_display = ("title", "klass", "given", "lms_assignment_id", "fetched_at")
    list_filter = ("klass", "given")
    search_fields = ("title",)
    readonly_fields = ("klass", "lms_assignment_id", "title", "lms_lesson_id", "given", "fetched_at")


@admin.register(AssignProposal)
class AssignProposalAdmin(ReviewActionsMixin, admin.ModelAdmin):
    list_display = ("assessment", "klass", "lesson_date", "begin_at", "end_at", "allow_late", "flags", "status", "run")
    list_filter = ("status", "run__klass", "run", "flags")
    list_select_related = ("assessment", "run__klass")
    readonly_fields = ("run", "assessment", "lesson_date", "begin_at", "end_at", "allow_late", "flags",
                       "status", "error", "applied_at")
