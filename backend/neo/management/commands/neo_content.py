"""
محرك المحتوى من سطر الأوامر، بلا سكربتات مؤقتة:
python manage.py neo_content status                      → الدروس الناقصة ونواقصها والاقتراحات المنتظرة لكل صف
python manage.py neo_content plan --class 602598          → مهمة اقتراح (بعد تدقيق الجودة)
python manage.py neo_content approve --run 89 [--kind assessment] [--lesson 16646650]
python manage.py neo_content apply --run 89 [--lesson ..] → مهمة إضافة المعتمد ثم تدقيق تلقائي
الاعتماد قرار المعلم: الأمر ينفّذه بطلبه الصريح فقط.
"""
from django.core.management.base import BaseCommand, CommandError

from neo.domain.quality import ISSUES
from neo.models import ContentProposal, LessonAudit, PlatformClass
from neo.services.job_service import JobService


class Command(BaseCommand):
    help = "محرك المحتوى: حالة، اقتراح، اعتماد، تطبيق."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "plan", "approve", "apply"])
        parser.add_argument("--class", dest="lms", type=int, action="append")
        parser.add_argument("--run", type=int)
        parser.add_argument("--kind", choices=[k.value for k in ContentProposal.Kind])
        parser.add_argument("--lesson", type=int, help="lms_lesson_id")

    def handle(self, *args, action, lms, run, kind, lesson, **opts):
        return getattr(self, action)(lms=lms, run=run, kind=kind, lesson=lesson)

    def status(self, **_):
        for k in PlatformClass.objects.order_by("lms_id"):
            audits = LessonAudit.objects.filter(lesson__klass=k).select_related("lesson").order_by("lesson__position")
            incomplete = [a for a in audits if a.issues]
            pending = ContentProposal.objects.filter(run__klass=k, status="pending").count()
            self.stdout.write(f"{k.name} ({k.lms_id}): مكتمل {audits.count() - len(incomplete)}/{audits.count()}"
                              f"، اقتراحات منتظرة {pending}")
            for a in incomplete:
                self.stdout.write(f"  {a.lesson.position:>2} {a.lesson.title[:40]:<40} "
                                  + "، ".join(ISSUES.get(i, i) for i in a.issues))

    def plan(self, lms, **_):
        if not lms:
            raise CommandError("--class مطلوب")
        job, created = JobService().enqueue("content_plan", {"classes": lms})
        self.stdout.write(f"مهمة الاقتراح #{job.pk}" + ("" if created else " (كانت في الطابور)"))

    def approve(self, run, kind, lesson, **_):
        if not run:
            raise CommandError("--run مطلوب")
        qs = ContentProposal.objects.filter(run_id=run, status=ContentProposal.Status.PENDING)
        if kind:
            qs = qs.filter(kind=kind)
        if lesson:
            qs = qs.filter(lesson__lms_lesson_id=lesson)
        self.stdout.write(f"اعتُمد {qs.update(status=ContentProposal.Status.APPROVED)}")

    def apply(self, run, lesson, **_):
        if not run:
            raise CommandError("--run مطلوب")
        job, created = JobService().enqueue("content_apply", {"run": run, "lesson": lesson})
        self.stdout.write(f"مهمة الإضافة #{job.pk}" + ("" if created else " (كانت في الطابور)"))
