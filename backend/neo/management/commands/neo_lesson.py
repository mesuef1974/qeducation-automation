"""
python manage.py neo_lesson --spec lesson.json            → معاينة ما سيُنشأ (بلا كتابة)
python manage.py neo_lesson --spec lesson.json --apply    → إنشاء الدرس كاملًا مخفيًا بعد اعتماد المعلم للمعاينة
الطرفية في ويندوز تشوّه العربية، فالتقرير الكامل يُكتب ملف UTF-8 ويُطبع مساره.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from neo.domain import lesson_spec
from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.services import lesson_build_service as build
from neo.services import pipeline, safety
from neo.services.job_service import JobService


class Command(BaseCommand):
    help = "درس جديد كامل من مواصفة JSON: معاينة، ثم إنشاء مخفي بالاعتماد."

    def add_arguments(self, parser):
        parser.add_argument("--spec", required=True, type=Path)
        parser.add_argument("--apply", action="store_true", help="الكتابة على المنصة (بعد اعتماد المعاينة)")
        parser.add_argument("--queue", action="store_true",
                            help="بدل التنفيذ هنا: يُطابور مهمة للعامل فتظهر في «مباشر» والرسم (المواصفة في .local/lessons)")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, spec, apply, queue, show_browser, **opts):
        try:
            parsed = lesson_spec.load(spec)
        except lesson_spec.SpecError as exc:
            raise CommandError(str(exc)) from exc
        for line in build.describe(parsed):
            self.stdout.write(line)
        if not apply:
            self.stdout.write(self.style.WARNING("معاينة فقط: أعد التشغيل مع --apply بعد الاعتماد."))
            return
        if queue:
            lessons = pipeline.lesson_dir().resolve()
            if lessons not in spec.resolve().parents:
                raise CommandError(f"للطابور تُوضع المواصفة وملفاتها في {lessons}")
            job, created = JobService().enqueue("lesson_build", {"spec": spec.resolve().relative_to(lessons).as_posix()})
            self.stdout.write(f"مهمة #{job.pk} {'أُنشئت' if created else 'قائمة بالفعل'}: يتابعها العامل وتظهر في «مباشر».")
            return
        try:
            run = build.LessonBuildService().build(parsed, lambda: NeoClient(headless=not show_browser))
        except (NotLoggedIn, PlatformError, build.BuildError, safety.WritesHalted) as exc:
            raise CommandError(str(exc)) from exc
        report = settings.NEO_PREP["cache_dir"] / "reports" / f"lesson_{run.pk}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(run.summary, ensure_ascii=False, indent=1), encoding="utf-8")
        write = self.style.SUCCESS if run.ok else self.style.ERROR
        self.stdout.write(write(f"build #{run.pk} ok={run.ok} lesson={run.summary['lesson']} خطوات={len(run.summary['steps'])}"))
        if run.summary["stopped"]:
            self.stdout.write(self.style.ERROR(f"توقف: {run.summary['stopped']}"))
        self.stdout.write(f"report: {report}")
