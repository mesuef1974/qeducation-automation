"""
python manage.py neo_publish                                  → جلب الدروس + اقتراح الإظهار والنقاط (قراءة فقط)
python manage.py neo_publish --apply RUN [--approve all] [--limit N]  → الإظهار وإضافة النقاط (كتابة) ثم التحقق
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.management.report import write_runs
from neo.services import pipeline
from neo.services.sync_service import NoActiveClasses, active_classes


class Command(BaseCommand):
    help = "نشر الدروس للطلاب: الرؤية ونقاط الإنجاز."

    def add_arguments(self, parser):
        parser.add_argument("--apply", type=int, metavar="RUN_ID")
        parser.add_argument("--approve", choices=["all"])
        parser.add_argument("--limit", type=int, default=None, help="تطبيق أول N فقط (للتجربة)")
        parser.add_argument("--class", dest="klass", type=int, action="append", metavar="LMS_ID",
                            help="حصر العمل في صف (يتكرر)؛ الافتراضي كل الصفوف المفعّلة")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, apply, approve, limit, show_browser, **opts):
        factory = lambda: NeoClient(headless=not show_browser)  # noqa: E731
        try:
            if apply:
                runs = pipeline.publish_apply(apply, factory, timezone.localdate(), approve, limit)
            else:
                runs = pipeline.publish_plan(active_classes(opts["klass"]), factory)
        except (NotLoggedIn, PlatformError, NoActiveClasses, pipeline.PipelineError) as exc:
            raise CommandError(str(exc)) from exc
        write_runs(self.stdout, self.style, runs)
