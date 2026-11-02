"""
python manage.py plan_file template OUT.xlsx              → قالب فارغ لخطة جديدة
python manage.py plan_file check PATH [PATH ...]          → فحص ملف خطة أو مجلد دون استيراد
python manage.py plan_file export --plan ID [--out DIR]   → تصدير خطة مخزّنة إلى ملف خطة
python manage.py plan_file export --all [--out DIR]       → تصدير كل الخطط
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from curriculum.domain.plan_spec import PlanFileError
from curriculum.infrastructure.plan_workbook import plan_files, read_plan, write_plan
from curriculum.models import Plan
from curriculum.services.plan_export import default_file_name, spec_from_plan


class Command(BaseCommand):
    help = "ملفات الخطط الموحّدة: قالب وفحص وتصدير."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("template").add_argument("out", type=Path)
        sub.add_parser("check").add_argument("paths", type=Path, nargs="+")
        exp = sub.add_parser("export")
        group = exp.add_mutually_exclusive_group(required=True)
        group.add_argument("--plan", type=int, metavar="PLAN_ID")
        group.add_argument("--all", action="store_true")
        exp.add_argument("--out", type=Path, default=settings.PLANS_DIR)
        exp.add_argument("--force", action="store_true", help="استبدال ملف موجود")

    def handle(self, *args, action, **opts):
        if action == "template":
            path = write_plan(None, opts["out"])
            self.stdout.write(self.style.SUCCESS(f"قالب: {path}"))
        elif action == "check":
            self._check(opts["paths"])
        else:
            self._export(opts)

    def _check(self, paths):
        failed = 0
        for path in [f for p in paths for f in plan_files(p)]:
            try:
                spec = read_plan(path)
            except PlanFileError as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(str(exc)))
                continue
            self.stdout.write(self.style.SUCCESS(
                f"سليم: {path.name} ← {spec} | {len(spec.lessons())} درسًا، {len(spec.entries)} بندًا، "
                f"{sum(spec.week_totals().values())} حصة"))
        if failed:
            raise CommandError(f"{failed} ملف فيه أخطاء")

    def _export(self, opts):
        plans = Plan.objects.all() if opts["all"] else Plan.objects.filter(pk=opts["plan"])
        if not plans:
            raise CommandError("لا توجد خطة بهذا الرقم")
        for plan in plans:
            spec = spec_from_plan(plan)
            path = opts["out"] / default_file_name(spec)
            if path.exists() and not opts["force"]:
                raise CommandError(f"الملف موجود: {path} (استعمل --force للاستبدال)")
            write_plan(spec, path)
            read_plan(path)  # ذهاب وإياب: الملف المكتوب يجب أن يجتاز الفحص
            self.stdout.write(self.style.SUCCESS(f"#{plan.pk} → {path}"))
