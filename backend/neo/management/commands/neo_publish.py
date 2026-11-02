"""
python manage.py neo_publish                                  → جلب الدروس + اقتراح الإظهار والنقاط (قراءة فقط)
python manage.py neo_publish --apply RUN [--approve all] [--limit N]  → الإظهار وإضافة النقاط (كتابة) ثم التحقق
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.management.commands.neo_verify import verify
from neo.models import PublishProposal, SyncRun
from neo.services.publish_service import PublishService
from neo.services.sync_service import NoActiveClasses, SyncService, active_classes


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
        svc = PublishService()
        factory = lambda: NeoClient(headless=not show_browser)  # noqa: E731
        try:
            if apply:
                run = SyncRun.objects.filter(pk=apply, kind=SyncRun.Kind.PUBLISH_PLAN).first()
                if not run:
                    raise CommandError(f"لا توجد عملية اقتراح نشر #{apply}")
                if approve:
                    self.stdout.write(f"اعتُمد {svc.approve(apply)} اقتراح.")
                if not run.publish_proposals.filter(status=PublishProposal.Status.APPROVED).exists():
                    raise CommandError("لا توجد اقتراحات معتمدة")
                log = svc.apply(run, factory, limit)
                self.stdout.write(self.style.SUCCESS(f"[نشر #{log.pk}] {json.dumps(log.summary, ensure_ascii=False)}"))
                verify(self.stdout, self.style, [run.klass], factory, timezone.localdate())
                return
            classes = active_classes(opts["klass"])
            SyncService().fetch(classes, factory)
            games = svc.fetch(classes, factory)
            for k in classes:
                r = svc.plan(k, games[k.pk])
                self.stdout.write(self.style.SUCCESS(f"[اقتراح نشر #{r.pk}] {k}"))
                self.stdout.write(json.dumps(r.summary, ensure_ascii=False, indent=1))
        except (NotLoggedIn, PlatformError, NoActiveClasses) as exc:
            raise CommandError(str(exc)) from exc
