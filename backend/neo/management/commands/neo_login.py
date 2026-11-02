from django.core.management.base import BaseCommand, CommandError

from neo.infrastructure.client import BrowserBusy, NeoClient


class Command(BaseCommand):
    help = "يفتح متصفحًا لتسجيل الدخول يدويًا إلى المنصة؛ تُحفظ الجلسة في .neo_profile."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=600, help="ثوانٍ انتظار الدخول")

    def handle(self, *args, timeout, **opts):
        self.stdout.write("سجّل الدخول في النافذة المفتوحة... (تُغلق تلقائيًا بعد الوصول للصفحة الرئيسية)")
        try:
            with NeoClient(headless=False) as client:
                client.login_interactive(timeout)
        except BrowserBusy as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("تم حفظ الجلسة."))
