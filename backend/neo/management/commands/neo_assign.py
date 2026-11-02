"""
python manage.py neo_assign                                   → جلب التقييمات + اقتراح الإسناد (قراءة فقط)
python manage.py neo_assign --apply RUN [--approve all] [--limit N]   → ضبط المواعيد والإسناد (كتابة)
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.management.report import write_runs
from neo.services import pipeline
from neo.services.sync_service import NoActiveClasses, active_classes


class Command(BaseCommand):
    help = "إسناد التقييمات وفق تواريخ الدروس."

    def add_arguments(self, parser):
        parser.add_argument("--today", type=date.fromisoformat, default=None)
        parser.add_argument("--apply", type=int, metavar="RUN_ID")
        parser.add_argument("--approve", choices=["all", "future"])
        parser.add_argument("--limit", type=int, default=None, help="تطبيق أول N فقط (للتجربة)")
        parser.add_argument("--class", dest="klass", type=int, action="append", metavar="LMS_ID",
                            help="حصر العمل في صف (يتكرر)؛ الافتراضي كل الصفوف المفعّلة")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, today, apply, approve, limit, show_browser, **opts):
        factory = lambda: NeoClient(headless=not show_browser)  # noqa: E731
        today = today or timezone.localdate()
        try:
            if apply:
                runs = pipeline.assign_apply(apply, factory, today, approve, limit)
            else:
                runs = pipeline.assign_plan(active_classes(opts["klass"]), factory, today)
        except (NotLoggedIn, PlatformError, NoActiveClasses, pipeline.PipelineError) as exc:
            raise CommandError(str(exc)) from exc
        write_runs(self.stdout, self.style, runs)
