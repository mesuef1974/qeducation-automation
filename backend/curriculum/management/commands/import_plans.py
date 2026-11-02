"""
python manage.py import_plans                 → كل ملفات الخطط في PLANS_DIR (plans/)
python manage.py import_plans PATH [PATH ...] → ملف خطة أو مجلد بعينه
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from curriculum.domain.plan_spec import PlanFileError
from curriculum.services.import_service import PlanImportService


class Command(BaseCommand):
    help = "استيراد ملفات الخطط الفصلية (تراكمي: يحدّث الخطط الواردة ولا يمس غيرها)."

    def add_arguments(self, parser):
        parser.add_argument("paths", type=Path, nargs="*")

    def handle(self, *args, paths: list[Path], **options):
        for source in paths or [settings.PLANS_DIR]:
            try:
                result = PlanImportService(source).run()
            except (FileNotFoundError, PlanFileError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.SUCCESS(
                f"{source}: plans={result.plans} lessons={result.lessons} "
                f"entries={result.entries} outcomes={result.outcomes}"))
