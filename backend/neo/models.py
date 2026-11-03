from django.db import models

from curriculum.models import Plan


class ActiveClassQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True).select_related("plan")


class PlatformClass(models.Model):
    """صف على المنصة مربوط بخطته الفصلية. يُضاف من لوحة الإدارة أو بأمر neo_class."""

    lms_id = models.PositiveIntegerField("LMS ID", unique=True)
    name = models.CharField("الاسم", max_length=120)
    # الاستيراد تراكمي ويحفظ مفتاح الخطة، فالربط المباشر آمن؛ PROTECT يمنع حذف خطة مستخدمة
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="platform_classes", verbose_name="الخطة")
    active = models.BooleanField("مفعّل", default=True, help_text="الصفوف غير المفعّلة تُستثنى من كل المهام")
    # تتقدّم على NEO_PUBLISH_POLICY؛ الفارغ يأخذ القيمة العامة
    points_game = models.CharField("لعبة النقاط", max_length=120, blank=True,
                                   help_text="اسم اللعبة كما في المنصة، مثل «نجوم الرياضيات»")
    points = models.PositiveSmallIntegerField("نقاط الإنجاز", null=True, blank=True, help_text="0 = بلا نقاط")
    last_fetched_at = models.DateTimeField("آخر جلب", null=True, blank=True)

    objects = ActiveClassQuerySet.as_manager()

    class Meta:
        verbose_name = "صف على المنصة"
        verbose_name_plural = "الصفوف على المنصة"
        ordering = ["-active", "name"]

    def __str__(self):
        return self.name


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
    hidden = models.BooleanField("مخفي عن الطلاب", default=False)
    awards_points = models.BooleanField("يمنح النقاط", default=False)
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
        PUBLISH_PLAN = "publish_plan", "اقتراح نشر"
        PUBLISH_APPLY = "publish_apply", "تطبيق نشر"
        VERIFY = "verify", "تحقق من منظور الطالب"
        AUDIT = "audit", "تدقيق جودة الدروس"
        CONTENT_PLAN = "content_plan", "اقتراح محتوى"
        CONTENT_APPLY = "content_apply", "تطبيق محتوى"

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


class PublishProposal(models.Model):
    """المهمة 3: إظهار الدرس للطلاب و/أو إضافة إجراء منح النقاط عند إنجازه."""

    Status = ProposalStatus

    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="publish_proposals",
                            verbose_name="العملية")
    lesson = models.ForeignKey(PlatformLesson, on_delete=models.CASCADE, related_name="publish_proposals",
                               verbose_name="الدرس")
    show = models.BooleanField("إظهار", default=False)
    add_points = models.BooleanField("منح النقاط", default=False)
    status = models.CharField("الحالة", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField("الخطأ", blank=True)
    applied_at = models.DateTimeField("وقت التطبيق", null=True, blank=True)

    class Meta:
        verbose_name = "اقتراح نشر"
        verbose_name_plural = "اقتراحات النشر"
        ordering = ["run", "lesson__position"]
        constraints = [models.UniqueConstraint(fields=["run", "lesson"], name="uq_publish_run_lesson")]

    def __str__(self):
        parts = [t for t, on in (("إظهار", self.show), ("نقاط", self.add_points)) if on]
        return f"{self.lesson} → {' + '.join(parts)}"


class ContentProposal(models.Model):
    """ما يُقترح إضافته إلى درس ناقص؛ يعدّله المعلم ويعتمده، ثم يُضاف دون المساس بالموجود."""

    class Kind(models.TextChoices):
        DESCRIPTION = "description", "الوصف"
        IMAGE = "image", "صورة البطاقة"
        SECTION = "section", "قسم تهيئة"
        ASSESSMENT = "assessment", "تقييم ذاتي التصحيح"
        OUTCOMES = "outcomes", "ربط نتاجات"

    Status = ProposalStatus

    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="content_proposals", verbose_name="العملية")
    lesson = models.ForeignKey(PlatformLesson, on_delete=models.CASCADE, related_name="content_proposals",
                               verbose_name="الدرس")
    kind = models.CharField("النوع", max_length=12, choices=Kind.choices)
    payload = models.JSONField("المحتوى")  # الوصف: text؛ الصورة: file وcolor وtitle؛ القسم: name وhtml
    status = models.CharField("الحالة", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField("الخطأ", blank=True)
    applied_at = models.DateTimeField("وقت التطبيق", null=True, blank=True)

    class Meta:
        verbose_name = "اقتراح محتوى"
        verbose_name_plural = "اقتراحات المحتوى"
        ordering = ["lesson__position", "kind"]

    def __str__(self):
        return f"{self.lesson}: {self.get_kind_display()} - {self.get_status_display()}"


class Job(models.Model):
    """
    مهمة تعمل على المنصة، تطلبها الواجهة وينفّذها عامل واحد (neo_worker) بالترتيب.
    عامل واحد = متصفح واحد بملف الدخول، فلا تتزاحم المهام عليه.
    """

    class Kind(models.TextChoices):
        LOGIN = "login", "تسجيل الدخول"
        SYNC_PLAN = "sync_plan", "جلب واقتراح التواريخ"
        SYNC_APPLY = "sync_apply", "تطبيق التواريخ"
        ASSIGN_PLAN = "assign_plan", "جلب واقتراح الإسناد"
        ASSIGN_APPLY = "assign_apply", "تطبيق الإسناد"
        PUBLISH_PLAN = "publish_plan", "جلب واقتراح النشر"
        PUBLISH_APPLY = "publish_apply", "تطبيق النشر ثم التحقق"
        VERIFY = "verify", "التحقق من منظور الطالب"
        WEEKLY = "weekly", "الدورة الأسبوعية"
        AUDIT = "audit", "تدقيق جودة الدروس"
        CONTENT_PLAN = "content_plan", "اقتراح المحتوى"
        CONTENT_APPLY = "content_apply", "إضافة المحتوى المعتمد"

    class Status(models.TextChoices):
        QUEUED = "queued", "في الانتظار"
        RUNNING = "running", "قيد التشغيل"
        DONE = "done", "تمت"
        FAILED = "failed", "فشلت"

    class Error(models.TextChoices):
        NONE = "", "-"
        SESSION = "session", "انتهت جلسة الدخول"
        BUSY = "busy", "المتصفح مشغول"
        INPUT = "input", "طلب غير صالح"
        PLATFORM = "platform", "خطأ من المنصة"
        UNEXPECTED = "unexpected", "خطأ غير متوقع"

    ACTIVE = (Status.QUEUED, Status.RUNNING)

    kind = models.CharField("النوع", max_length=20, choices=Kind.choices)
    params = models.JSONField("المعطيات", default=dict, blank=True)
    # النوع + المعطيات؛ يمنع تكرار المهمة نفسها ما دامت نشطة (Idempotent)
    key = models.CharField("المفتاح", max_length=255, editable=False)
    status = models.CharField("الحالة", max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    created_at = models.DateTimeField("الطلب", auto_now_add=True)
    started_at = models.DateTimeField("البداية", null=True, blank=True)
    finished_at = models.DateTimeField("النهاية", null=True, blank=True)
    error_kind = models.CharField("نوع الخطأ", max_length=12, choices=Error.choices, blank=True)
    error = models.TextField("الخطأ", blank=True)
    runs = models.ManyToManyField(SyncRun, blank=True, related_name="jobs", verbose_name="العمليات الناتجة")
    report = models.JSONField("التقرير", default=dict, blank=True)  # الدورة الأسبوعية: ما اعتُمد وما بقي ولماذا

    class Meta:
        verbose_name = "مهمة"
        verbose_name_plural = "المهام"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["key"], condition=models.Q(status__in=["queued", "running"]),
                                               name="uq_active_job")]

    def __str__(self):
        return f"#{self.pk} {self.get_kind_display()} - {self.get_status_display()}"


class WorkerHeartbeat(models.Model):
    """
    نبض عامل المهام (صف واحد). حالة المهام وحدها لا تكفي: مهمة «قيد التشغيل» يبقى عليها العامل
    إن أُغلقت طرفيته فجأة، فتظن الواجهة أنه يعمل.
    """

    seen_at = models.DateTimeField("آخر نبض")
    pid = models.PositiveIntegerField("رقم العملية")

    class Meta:
        verbose_name = "نبض العامل"
        verbose_name_plural = "نبض العامل"

    def __str__(self):
        return f"العامل {self.pid} - {self.seen_at:%H:%M:%S}"


class LessonAudit(models.Model):
    """نتيجة تدقيق جودة درس (قراءة فقط): ما ينقصه ليجذب الطالب ويُعلّمه."""

    lesson = models.OneToOneField(PlatformLesson, on_delete=models.CASCADE, related_name="audit", verbose_name="الدرس")
    image_default = models.BooleanField("صورة عامة")
    sections = models.JSONField("أنواع الأقسام", default=list)  # بترتيبها، مثل ["عرض", "فيديو", "تقييم"]
    has_outcomes = models.BooleanField("مربوط بنتاج")
    issues = models.JSONField("النواقص", default=list)  # رموز من domain.quality.ISSUES
    audited_at = models.DateTimeField("وقت التدقيق")

    class Meta:
        verbose_name = "تدقيق درس"
        verbose_name_plural = "تدقيق الدروس"

    @property
    def complete(self) -> bool:
        return not self.issues

    def __str__(self):
        return f"{self.lesson}: {len(self.issues)} نواقص"


class ScorecardSnapshot(models.Model):
    """لقطة يومية لبطاقة الأداء؛ أول لقطة هي خط الأساس الذي يُقاس عليه التحسن."""

    day = models.DateField("اليوم", unique=True)
    data = models.JSONField("القيم")

    class Meta:
        ordering = ["-day"]
        verbose_name = "لقطة بطاقة الأداء"
        verbose_name_plural = "لقطات بطاقة الأداء"

    def __str__(self):
        return f"بطاقة الأداء {self.day}"
