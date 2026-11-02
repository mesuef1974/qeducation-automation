"""
python manage.py neo_class list                                  → الصفوف وخططها
python manage.py neo_class plans                                 → الخطط المتاحة للربط وأرقامها
python manage.py neo_class add LMS_ID --plan PLAN_ID --name "…"  → إضافة صف أو تغيير خطته
python manage.py neo_class disable|enable LMS_ID                 → استثناء صف من المهام أو إعادته
"""
from django.core.management.base import BaseCommand, CommandError

from curriculum.models import Plan
from neo.models import PlatformClass
from neo.services.class_service import ClassService


class Command(BaseCommand):
    help = "إدارة صفوف المنصة وربطها بالخطط الفصلية."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("list")
        sub.add_parser("plans")
        add = sub.add_parser("add")
        add.add_argument("lms_id", type=int)
        add.add_argument("--plan", type=int, required=True, metavar="PLAN_ID")
        add.add_argument("--name")
        for action in ("enable", "disable"):
            sub.add_parser(action).add_argument("lms_id", type=int)

    def handle(self, *args, action, **opts):
        svc = ClassService()
        try:
            if action == "list":
                for k in PlatformClass.objects.select_related("plan"):
                    state = "مفعّل" if k.active else "موقوف"
                    self.stdout.write(f"{k.lms_id}  {k.name}  [{state}]  ← خطة #{k.plan_id}: {k.plan}")
            elif action == "plans":
                for p in Plan.objects.all():
                    self.stdout.write(f"#{p.pk}  {p}")
            elif action == "add":
                k, created = svc.register(opts["lms_id"], opts["plan"], opts.get("name"))
                self.stdout.write(self.style.SUCCESS(f"{'أُضيف' if created else 'حُدّث'}: {k} ← {k.plan}"))
            else:
                k = svc.set_active(opts["lms_id"], action == "enable")
                self.stdout.write(self.style.SUCCESS(f"{k}: {'مفعّل' if k.active else 'موقوف'}"))
        except (LookupError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
