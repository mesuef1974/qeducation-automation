from django.db import models


class SourceDocument(models.Model):
    form_code = models.CharField("رمز النموذج", max_length=30)
    issue_no = models.PositiveSmallIntegerField("رقم الإصدار")
    issue_date = models.DateField("تاريخ الإصدار")
    classification = models.CharField("التصنيف", max_length=30)
    department = models.CharField("الجهة", max_length=120)
    file_name = models.CharField("اسم الملف", max_length=255, unique=True)
    page_count = models.PositiveSmallIntegerField("عدد الصفحات")

    class Meta:
        verbose_name = "وثيقة مصدر"
        verbose_name_plural = "وثائق المصدر"

    def __str__(self):
        return self.file_name


# هوية الخطة الطبيعية: تسمح بخطط لمواد وفصول ومسارات متعددة للمستوى نفسه
PLAN_KEY_FIELDS = ("subject", "academic_year", "term_no", "grade_level", "tracks", "shift")


class Plan(models.Model):
    document = models.OneToOneField(SourceDocument, on_delete=models.PROTECT, verbose_name="الوثيقة")
    subject = models.CharField("المادة", max_length=60)
    academic_year = models.CharField("العام الأكاديمي", max_length=9)
    term_no = models.PositiveSmallIntegerField("الفصل")
    grade_level = models.PositiveSmallIntegerField("المستوى")
    tracks = models.CharField("المسارات", max_length=60, blank=True)
    shift = models.CharField("الفترة", max_length=20)
    platform_class = models.CharField("الصف على المنصة", max_length=60, blank=True)

    class Meta:
        verbose_name = "خطة فصلية"
        verbose_name_plural = "الخطط الفصلية"
        ordering = ["-academic_year", "-term_no", "subject", "grade_level"]
        constraints = [models.UniqueConstraint(fields=list(PLAN_KEY_FIELDS), name="uq_plan_identity")]

    def __str__(self):
        tracks = f" ({self.tracks})" if self.tracks else ""
        return f"{self.subject} - المستوى {self.grade_level}{tracks} - {self.academic_year} ف{self.term_no}"


class Unit(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="units", verbose_name="الخطة")
    unit_no = models.PositiveSmallIntegerField("رقم الوحدة")
    title = models.CharField("اسم الوحدة", max_length=120)
    domain = models.CharField("المجال", max_length=120)

    class Meta:
        verbose_name = "وحدة"
        verbose_name_plural = "الوحدات"
        ordering = ["plan", "unit_no"]
        constraints = [models.UniqueConstraint(fields=["plan", "unit_no"], name="uq_unit_plan_no")]

    def __str__(self):
        return f"الوحدة {self.unit_no}: {self.title}"


class Week(models.Model):
    class Type(models.TextChoices):
        TEACHING = "تدريس", "تدريس"
        BREAK = "إجازة", "إجازة"

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="weeks", verbose_name="الخطة")
    week_no = models.PositiveSmallIntegerField("الأسبوع")
    start_date = models.DateField("من", db_index=True)
    end_date = models.DateField("إلى", db_index=True)
    week_type = models.CharField("النوع", max_length=10, choices=Type.choices)
    note = models.CharField("ملاحظة", max_length=255, blank=True)

    class Meta:
        verbose_name = "أسبوع"
        verbose_name_plural = "الأسابيع"
        ordering = ["plan", "week_no"]
        constraints = [models.UniqueConstraint(fields=["plan", "week_no"], name="uq_week_plan_no")]

    def __str__(self):
        return f"الأسبوع {self.week_no} ({self.start_date:%m/%d} - {self.end_date:%m/%d})"


class Lesson(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="lessons", verbose_name="الخطة")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="lessons", verbose_name="الوحدة")
    code = models.CharField("رمز الدرس", max_length=10)
    title = models.CharField("العنوان", max_length=200)
    in_schedule = models.BooleanField("في التوزيع الأسبوعي", default=True)
    total_periods = models.PositiveSmallIntegerField("مجموع الحصص", default=0)

    class Meta:
        verbose_name = "درس"
        verbose_name_plural = "الدروس"
        ordering = ["plan", "unit__unit_no", "id"]
        constraints = [models.UniqueConstraint(fields=["plan", "code"], name="uq_lesson_plan_code")]

    def __str__(self):
        return f"{self.code} {self.title}"


class ScheduleEntry(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="entries", verbose_name="الخطة")
    week = models.ForeignKey(Week, on_delete=models.CASCADE, related_name="entries", verbose_name="الأسبوع")
    seq = models.PositiveSmallIntegerField("الترتيب")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, null=True, blank=True, verbose_name="الوحدة")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="entries", verbose_name="الدرس")
    activity_type = models.CharField("النوع", max_length=40, db_index=True)
    title = models.CharField("العنوان", max_length=200)
    periods = models.PositiveSmallIntegerField("الحصص")

    class Meta:
        verbose_name = "بند توزيع"
        verbose_name_plural = "التوزيع الأسبوعي"
        ordering = ["plan", "week__week_no", "seq"]
        constraints = [models.UniqueConstraint(fields=["week", "seq"], name="uq_entry_week_seq")]

    def __str__(self):
        return f"{self.title} ({self.periods})"


class Competency(models.Model):
    name = models.CharField("الكفاية", max_length=80, unique=True)

    class Meta:
        verbose_name = "كفاية"
        verbose_name_plural = "الكفايات ومهارات القرن 21"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CoreValue(models.Model):
    name = models.CharField("القيمة", max_length=80, unique=True)

    class Meta:
        verbose_name = "قيمة"
        verbose_name_plural = "القيم والقضايا المشتركة"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OutcomeBlock(models.Model):
    """خلية مدموجة في الأصل: كفايات وقيم ومكتسبات لمدى أسابيع."""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="outcome_blocks", verbose_name="الخطة")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="outcome_blocks", verbose_name="الوحدة")
    week_from = models.PositiveSmallIntegerField("من أسبوع")
    week_to = models.PositiveSmallIntegerField("إلى أسبوع")
    competencies = models.ManyToManyField(Competency, verbose_name="الكفايات")
    values = models.ManyToManyField(CoreValue, verbose_name="القيم")

    class Meta:
        verbose_name = "كتلة مكتسبات"
        verbose_name_plural = "كتل المكتسبات"
        ordering = ["plan", "week_from"]
        constraints = [
            models.CheckConstraint(condition=models.Q(week_from__lte=models.F("week_to")), name="ck_block_weeks"),
        ]

    def __str__(self):
        return f"{self.unit} - الأسابيع {self.week_from}-{self.week_to}"


class LearningOutcome(models.Model):
    block = models.ForeignKey(OutcomeBlock, on_delete=models.CASCADE, related_name="outcomes", verbose_name="الكتلة")
    seq = models.PositiveSmallIntegerField("الترتيب")
    text = models.TextField("مكتسب التعلم")

    class Meta:
        verbose_name = "مكتسب تعلم"
        verbose_name_plural = "مكتسبات التعلم"
        ordering = ["block", "seq"]
        constraints = [models.UniqueConstraint(fields=["block", "seq"], name="uq_outcome_block_seq")]

    def __str__(self):
        return self.text[:80]


class CalendarEvent(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="events", verbose_name="الخطة")
    event_type = models.CharField("النوع", max_length=30)
    title = models.CharField("الحدث", max_length=120)
    start_date = models.DateField("من")
    end_date = models.DateField("إلى")
    note = models.CharField("ملاحظة", max_length=120, blank=True)

    class Meta:
        verbose_name = "حدث"
        verbose_name_plural = "التقويم"
        ordering = ["start_date", "plan"]

    def __str__(self):
        return self.title


class EnrichmentItem(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="enrichment", verbose_name="الخطة")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="enrichment", verbose_name="الدرس")
    detail = models.CharField("المحتوى الإثرائي", max_length=200, blank=True)

    class Meta:
        verbose_name = "بند إثرائي"
        verbose_name_plural = "الدروس والأمثلة الإثرائية"
        ordering = ["plan", "id"]

    def __str__(self):
        return f"{self.lesson} - {self.detail or 'الدرس كاملًا'}"


class Guideline(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="guidelines", verbose_name="الخطة")
    seq = models.PositiveSmallIntegerField("الترتيب")
    title = models.CharField("العنوان", max_length=120)
    body = models.TextField("النص")

    class Meta:
        verbose_name = "إرشاد"
        verbose_name_plural = "الإرشادات العامة"
        ordering = ["plan", "seq"]
        constraints = [models.UniqueConstraint(fields=["plan", "seq"], name="uq_guideline_plan_seq")]

    def __str__(self):
        return self.title


class TeachingStep(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="methodology", verbose_name="الخطة")
    seq = models.PositiveSmallIntegerField("الترتيب")
    component = models.CharField("الجزئية", max_length=120)
    procedure = models.CharField("الإجراء", max_length=255)

    class Meta:
        verbose_name = "خطوة منهجية"
        verbose_name_plural = "منهجية التدريس"
        ordering = ["plan", "seq"]
        constraints = [models.UniqueConstraint(fields=["plan", "seq"], name="uq_step_plan_seq")]

    def __str__(self):
        return self.component
