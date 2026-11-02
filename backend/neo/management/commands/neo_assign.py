"""
python manage.py neo_assign                                   → جلب التقييمات + اقتراح الإسناد (قراءة فقط)
python manage.py neo_assign --apply RUN [--approve all] [--limit N]   → ضبط المواعيد والإسناد (كتابة)
"""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.models import AssignProposal, SyncRun
from neo.services.assign_service import AssignService
from neo.services.sync_service import SyncService


class Command(BaseCommand):
    help = "إسناد التقييمات وفق تواريخ الدروس."

    def add_arguments(self, parser):
        parser.add_argument("--today", type=date.fromisoformat, default=None)
        parser.add_argument("--apply", type=int, metavar="RUN_ID")
        parser.add_argument("--approve", choices=["all", "future"])
        parser.add_argument("--limit", type=int, default=None, help="تطبيق أول N فقط (للتجربة)")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, today, apply, approve, limit, show_browser, **opts):
        svc = AssignService()
        factory = lambda: NeoClient(headless=not show_browser)  # noqa: E731
        today = today or timezone.localdate()
        try:
            if apply:
                run = SyncRun.objects.filter(pk=apply, kind=SyncRun.Kind.ASSIGN_PLAN).first()
                if not run:
                    raise CommandError(f"لا توجد عملية اقتراح إسناد #{apply}")
                if approve:
                    n = svc.approve(apply, None if approve == "all" else today)
                    self.stdout.write(f"اعتُمد {n} اقتراح.")
                if not run.assign_proposals.filter(status=AssignProposal.Status.APPROVED).exists():
                    raise CommandError("لا توجد اقتراحات معتمدة")
                log = svc.apply(run, factory, today, limit)
                self.stdout.write(self.style.SUCCESS(f"[إسناد #{log.pk}] {json.dumps(log.summary, ensure_ascii=False)}"))
                return
            classes = SyncService().ensure_classes()
            svc.fetch(classes, factory)
            for k in classes:
                r = svc.plan(k, today)
                self.stdout.write(self.style.SUCCESS(f"[اقتراح إسناد #{r.pk}] {k}"))
                self.stdout.write(json.dumps(r.summary, ensure_ascii=False, indent=1))
        except (NotLoggedIn, PlatformError) as exc:
            raise CommandError(str(exc)) from exc
