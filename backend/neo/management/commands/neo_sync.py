"""
python manage.py neo_sync                → جلب + اقتراح تواريخ لكل الصفوف (قراءة فقط من المنصة)
python manage.py neo_sync --no-fetch     → اقتراح من آخر بيانات مجلوبة
python manage.py neo_sync --apply RUN    → تطبيق الاقتراحات المعتمدة في عملية الاقتراح RUN (كتابة)
"""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.models import DateProposal, SyncRun
from neo.services.sync_service import SyncService


class Command(BaseCommand):
    help = "مزامنة دروس المنصة مع الخطة الفصلية."

    def add_arguments(self, parser):
        parser.add_argument("--no-fetch", action="store_true")
        parser.add_argument("--today", type=date.fromisoformat, default=None)
        parser.add_argument("--apply", type=int, metavar="RUN_ID")
        parser.add_argument("--approve", choices=["future", "all"],
                            help="مع --apply: يعتمد المعلّق أولًا (future = من اليوم فصاعدًا)")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, no_fetch, today, apply, approve, show_browser, **opts):
        svc = SyncService()
        try:
            if apply:
                if approve:
                    n = svc.approve(apply, only_from=None if approve == "all" else (today or timezone.localdate()))
                    self.stdout.write(f"اعتُمد {n} اقتراح.")
                return self._apply(svc, apply, show_browser)
            classes = svc.ensure_classes()
            if not no_fetch:
                for k, r in zip(classes, svc.fetch(classes, lambda: NeoClient(headless=not show_browser))):
                    self.stdout.write(f"[جلب] {k}: {json.dumps(r.summary, ensure_ascii=False)}")
            for k in classes:
                r = svc.plan(k, today or timezone.localdate())
                self.stdout.write(self.style.SUCCESS(f"[اقتراح #{r.pk}] {k}"))
                self.stdout.write(json.dumps(r.summary, ensure_ascii=False, indent=1))
        except (NotLoggedIn, PlatformError) as exc:
            raise CommandError(str(exc)) from exc

    def _apply(self, svc, run_id, show_browser):
        run = SyncRun.objects.filter(pk=run_id, kind=SyncRun.Kind.PLAN).first()
        if not run:
            raise CommandError(f"لا توجد عملية اقتراح #{run_id}")
        n = run.proposals.filter(status=DateProposal.Status.APPROVED).count()
        if not n:
            raise CommandError("لا توجد اقتراحات معتمدة - اعتمدها من لوحة الإدارة أولًا")
        log = svc.apply(run, lambda: NeoClient(headless=not show_browser))
        self.stdout.write(self.style.SUCCESS(f"[تطبيق #{log.pk}] {json.dumps(log.summary, ensure_ascii=False)}"))
