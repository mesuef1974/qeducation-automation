"""
python manage.py neo_verify [--class LMS_ID]   → جلب الدروس + التحقق مما يراه الطالب (قراءة فقط)
"""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.services.sync_service import NoActiveClasses, SyncService, active_classes
from neo.services.verify_service import VerifyService


def verify(stdout, style, classes, factory, today):
    """يُستدعى أيضًا بعد تطبيق النشر."""
    SyncService().fetch(classes, factory)
    for r in VerifyService().run(classes, factory, today):
        write = style.SUCCESS if r.ok else style.ERROR
        stdout.write(write(f"[تحقق #{r.pk}] {r.klass} - {'سليم' if r.ok else 'دروس ماضية لا يراها الطالب'}"))
        stdout.write(json.dumps(r.summary, ensure_ascii=False, indent=1))


class Command(BaseCommand):
    help = "التحقق من الدروس التي يراها الطالب فعلًا."

    def add_arguments(self, parser):
        parser.add_argument("--today", type=date.fromisoformat, default=None)
        parser.add_argument("--class", dest="klass", type=int, action="append", metavar="LMS_ID",
                            help="حصر العمل في صف (يتكرر)؛ الافتراضي كل الصفوف المفعّلة")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, today, show_browser, **opts):
        try:
            verify(self.stdout, self.style, active_classes(opts["klass"]),
                   lambda: NeoClient(headless=not show_browser), today or timezone.localdate())
        except (NotLoggedIn, PlatformError, NoActiveClasses) as exc:
            raise CommandError(str(exc)) from exc
