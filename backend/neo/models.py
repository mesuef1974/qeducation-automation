from django.db import models

from curriculum.models import Plan


class PlatformClass(models.Model):
    lms_id = models.PositiveIntegerField("LMS ID", unique=True)
    name = models.CharField("الاسم", max_length=120)
    # ربط بالمستوى لا بمفتاح الخطة: استيراد الخطط يعيد إنشاءها
    grade_level = models.PositiveSmallIntegerField("المستوى")
    last_fetched_at = models.DateTimeField("آخر جلب", null=True, blank=True)

    class Meta:
        verbose_name = "صف على المنصة"
        verbose_name_plural = "الصفوف على المنصة"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def plan(self) -> Plan:
        return Plan.objects.get(grade_level=self.grade_level)


class TimetableSlot(models.Model):
    WEEKDAYS = [(6, "الأحد"), (0, "الإثنين"), (1, "الثلاثاء"), (2, "الأربعاء"), (3, "الخميس")]

    klass = models.ForeignKey(PlatformClass, on_delete=models.CASCADE, related_name="slots", verbose_name="الصف")
    weekday = models.PositiveSmallIntegerField("اليوم", choices=WEEKDAYS)  # Python weekday()
    period = models.PositiveSmallIntegerField("الحصة")

    class Meta:
        verbose_name = "حصة في الجدول"
        verbose_name_plural = "الجدول الدراسي"
        ordering = ["klass", "weekday", "period"]
        constraints = [models.UniqueConstraint(fields=["klass", "weekday", "period"], name="uq_slot")]

    def __str__(self):
        return f"{self.get_weekday_display()} - الحصة {self.period}"


class PlatformLesson(models.Model):
    klass = models.ForeignKey(PlatformClass, on_delete=models.CASCADE, related_name="lessons", verbose_name="الصف")
    lms_lesson_id = models.PositiveBigIntegerField("Lesson ID", unique=True)
    position = models.PositiveSmallIntegerField("الترتيب")
    title = models.CharField("العنوان", max_length=255)
    description = models.TextField("الوصف", blank=True)
    date = models.DateField("التاريخ", null=True, blank=True)
    period = models.PositiveSmallIntegerField("الحصة", null=True, blank=True)
    match_code = models.CharField("المطابقة الآلية", max_length=60, blank=True,
                                  help_text="رمز درس الخطة (مثل 2.1) أو نشاط غير درسي (مثل مراجعة واختبار وحدة#1)")
    match_score = models.FloatField("درجة المطابقة", null=True, blank=True)
    override_code = models.CharField("مطابقة يدوية", max_length=60, blank=True,
                                     help_text="تتقدّم على الآلية. ضع '-' لاعتبار الدرس خارج الخطة.")
    fetched_at = models.DateTimeField("وقت الجلب")

    class Meta:
        verbose_name = "درس على المنصة"
        verbose_name_plural = "الدروس على المنصة"
        ordering = ["klass", "position"]

    def __str__(self):
        return f"{self.position}. {self.title}"

    @property
    def effective_code(self) -> str:
        return self.override_code or self.match_code


class SyncRun(models.Model):
    class Kind(models.TextChoices):
        FETCH = "fetch", "جلب"
        PLAN = "plan", "اقتراح تواريخ"
        APPLY = "apply", "تطبيق"
        ASSIGN_PLAN = "assign_plan", "اقتراح إسناد"
        ASSIGN_APPLY = "assign_apply", "تطبيق إسناد"

    klass = models.ForeignKey(PlatformClass, on_delete=models.CASCADE, related_name="runs", verbose_name="الصف")
    kind = models.CharField("النوع", max_length=20, choices=Kind.choices)
    started_at = models.DateTimeField("البداية", auto_now_add=True)
    finished_at = models.DateTimeField("النهاية", null=True, blank=True)
    ok = models.BooleanField("نجح", default=False)
    summary = models.JSONField("الملخص", default=dict, blank=True)

    class Meta:
        verbose_name = "عملية مزامنة"
        verbose_name_plural = "سجل المزامنة"
        ordering = ["-started_at"]

    def __str__(self):
        return f"#{self.pk} {self.get_kind_display()} - {self.klass}"


class ProposalStatus(models.TextChoices):
    PENDING = "pending", "بانتظار المراجعة"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"
    APPLIED = "applied", "طُبّق"
    SKIPPED = "skipped", "تُخطّي"
    FAILED = "failed", "فشل"


class DateProposal(models.Model):
    Status = ProposalStatus

    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="proposals", verbose_name="العملية")
    lesson = models.ForeignKey(PlatformLesson, on_delete=models.CASCADE, related_name="proposals", verbose_name="الدرس")
    proposed_date = models.DateField("التاريخ المقترح")
    proposed_period = models.PositiveSmallIntegerField("الحصة المقترحة")
    plan_week_no = models.PositiveSmallIntegerField("أسبوع الخطة")
    flags = models.CharField("تنبيهات", max_length=255, blank=True)
    status = models.CharField("الحالة", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField("الخطأ", blank=True)
    applied_at = models.DateTimeField("وقت التطبيق", null=True, blank=True)

    class Meta:
        verbose_name = "اقتراح تاريخ"
        verbose_name_plural = "اقتراحات التواريخ"
        ordering = ["run", "lesson__position"]
        constraints = [models.UniqueConstraint(fields=["run", "lesson"], name="uq_proposal_run_lesson")]

    def __str__(self):
        return f"{self.lesson} → {self.proposed_date} ح{self.proposed_period}"


class PlatformAssessment(models.Model):
    klass = models.ForeignKey(PlatformClass, on_delete=models.CASCADE, related_name="assessments", verbose_name="الصف")
    lms_assignment_id = models.PositiveBigIntegerField("Assignment ID", unique=True)
    title = models.CharField("العنوان", max_length=255)
    lms_lesson_id = models.PositiveBigIntegerField("Lesson ID", null=True, blank=True)
    given = models.BooleanField("مُسند", default=False)
    fetched_at = models.DateTimeField("وقت الجلب")

    class Meta:
        verbose_name = "تقييم على المنصة"
        verbose_name_plural = "التقييمات على المنصة"
        ordering = ["klass", "title"]

    def __str__(self):
        return self.title

    @property
    def lesson(self) -> PlatformLesson | None:
        return PlatformLesson.objects.filter(lms_lesson_id=self.lms_lesson_id).first()


class AssignProposal(models.Model):
    Status = ProposalStatus

    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="assign_proposals", verbose_name="العملية")
    assessment = models.ForeignKey(PlatformAssessment, on_delete=models.CASCADE, related_name="proposals",
                                   verbose_name="التقييم")
    lesson_date = models.DateField("تاريخ الدرس")
    begin_at = models.DateTimeField("البداية")
    end_at = models.DateTimeField("الاستحقاق")
    allow_late = models.BooleanField("يسمح بالتأخير", default=True)
    flags = models.CharField("تنبيهات", max_length=255, blank=True)
    status = models.CharField("الحالة", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField("الخطأ", blank=True)
    applied_at = models.DateTimeField("وقت التطبيق", null=True, blank=True)

    class Meta:
        verbose_name = "اقتراح إسناد"
        verbose_name_plural = "اقتراحات الإسناد"
        ordering = ["run", "begin_at"]
        constraints = [models.UniqueConstraint(fields=["run", "assessment"], name="uq_assign_run_assessment")]

    def __str__(self):
        return f"{self.assessment} → {self.begin_at:%m-%d} / {self.end_at:%m-%d}"
