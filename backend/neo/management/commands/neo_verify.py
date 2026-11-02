"""
python manage.py neo_verify [--class LMS_ID]   → جلب الدروس + التحقق مما يراه الطالب (قراءة فقط)
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.management.report import write_runs
from neo.services import pipeline
from neo.services.sync_service import NoActiveClasses, active_classes


class Command(BaseCommand):
    help = "التحقق من الدروس التي يراها الطالب فعلًا."

    def add_arguments(self, parser):
        parser.add_argument("--today", type=date.fromisoformat, default=None)
        parser.add_argument("--class", dest="klass", type=int, action="append", metavar="LMS_ID",
                            help="حصر العمل في صف (يتكرر)؛ الافتراضي كل الصفوف المفعّلة")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, today, show_browser, **opts):
        try:
            runs = pipeline.verify(active_classes(opts["klass"]), lambda: NeoClient(headless=not show_browser),
                                   today or timezone.localdate())
        except (NotLoggedIn, PlatformError, NoActiveClasses) as exc:
            raise CommandError(str(exc)) from exc
        write_runs(self.stdout, self.style, runs)
