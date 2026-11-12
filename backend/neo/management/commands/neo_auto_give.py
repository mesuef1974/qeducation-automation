"""
python manage.py neo_auto_give          → حالة الإسناد التلقائي في إعدادات كل صف (قراءة فقط)
python manage.py neo_auto_give --off    → إطفاؤه (قرار المعلم: واجب الثلاثاء وتقييم الخميس تُسندهما الأتمتة)
python manage.py neo_auto_give --on     → إعادته
"""
from django.core.management.base import BaseCommand, CommandError

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.models import PlatformClass
from neo.services import safety

OPTIONS = ("auto_give_assignments", "auto_give_when_started")


class Command(BaseCommand):
    help = "الإسناد التلقائي للتقييمات في إعدادات الصف على المنصة: قراءة، أو إطفاء/تشغيل."

    def add_arguments(self, parser):
        g = parser.add_mutually_exclusive_group()
        g.add_argument("--off", action="store_true")
        g.add_argument("--on", action="store_true")

    def handle(self, *args, off, on, **opts):
        classes = [(k.lms_id, k.name) for k in PlatformClass.objects.filter(active=True)]
        if off or on:
            safety.require_writes_allowed()
        try:
            with NeoClient(headless=True) as c:  # لا ORM هنا
                for lms, name in classes:
                    for opt in OPTIONS:
                        changed = c.set_class_option(lms, opt, on) if (off or on) else False
                        state = c.class_option(lms, opt)
                        self.stdout.write(f"{lms} {opt}: {'on' if state else 'off'}{' (changed)' if changed else ''}")
        except (NotLoggedIn, PlatformError, safety.WritesHalted) as exc:
            raise CommandError(str(exc)) from exc
