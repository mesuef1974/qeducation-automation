"""
python manage.py neo_report_pdf   → نسخة المشاركة من تقرير SWOT بصيغة PDF (بلا أسماء طلاب، بثيم نهاري)
يطبع الصفحة من الخادم المحلي ليشمل الأرقام الحيّة؛ الناتج في docs/report/out/ (خارج المستودع).
"""
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8777/docs/report/platform_report.html?share"


class Command(BaseCommand):
    help = "نسخة المشاركة من تقرير SWOT بصيغة PDF."

    def handle(self, *args, **opts):
        out = settings.DOCS_DIR / "report" / "out" / f"swot_share_{date.today():%Y-%m-%d}.pdf"
        out.parent.mkdir(exist_ok=True)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel=settings.NEO_BROWSER_CHANNEL)
                page = browser.new_page()
                page.add_init_script("localStorage.setItem('theme', 'light')")  # الطباعة بالثيم النهاري
                page.goto(URL, wait_until="networkidle")
                page.wait_for_selector("html[data-live=ready]", timeout=10_000)
                page.evaluate("document.fonts.ready")
                page.emulate_media(media="print")
                page.pdf(path=str(out), format="A4", print_background=True,
                         margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
                browser.close()
        except PlaywrightError as exc:
            raise CommandError(f"تعذّرت الطباعة؛ تأكد أن الخادم يعمل على {URL.split('/docs')[0]}: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"نسخة المشاركة: {out}"))
