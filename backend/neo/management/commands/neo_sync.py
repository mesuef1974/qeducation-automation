"""
python manage.py neo_sync                → جلب + اقتراح تواريخ لكل الصفوف (قراءة فقط من المنصة)
python manage.py neo_sync --no-fetch     → اقتراح من آخر بيانات مجلوبة
python manage.py neo_sync --apply RUN    → تطبيق الاقتراحات المعتمدة في عملية الاقتراح RUN (كتابة)
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.management.report import write_runs
from neo.services import pipeline
from neo.services.sync_service import NoActiveClasses, active_classes


class Command(BaseCommand):
    help = "مزامنة دروس المنصة مع الخطة الفصلية."

    def add_arguments(self, parser):
        parser.add_argument("--no-fetch", action="store_true")
        parser.add_argument("--today", type=date.fromisoformat, default=None)
        parser.add_argument("--apply", type=int, metavar="RUN_ID")
        parser.add_argument("--approve", choices=["future", "all"],
                            help="مع --apply: يعتمد المعلّق أولًا (future = من اليوم فصاعدًا)")
        parser.add_argument("--class", dest="klass", type=int, action="append", metavar="LMS_ID",
                            help="حصر العمل في صف (يتكرر)؛ الافتراضي كل الصفوف المفعّلة")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, no_fetch, today, apply, approve, show_browser, **opts):
        factory = lambda: NeoClient(headless=not show_browser)
        today = today or timezone.localdate()
        try:
            if apply:
                runs = pipeline.sync_apply(apply, factory, today, approve)
            else:
                runs = pipeline.sync_plan(active_classes(opts["klass"]), factory, today, fetch=not no_fetch)
        except (NotLoggedIn, PlatformError, NoActiveClasses, pipeline.PipelineError) as exc:
            raise CommandError(str(exc)) from exc
        write_runs(self.stdout, self.style, runs)
