from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from curriculum.services.import_service import PlanImportService


class Command(BaseCommand):
    help = "استيراد الخطط الفصلية من قاعدة db/math_plans_2026_2027.db (يستبدل البيانات الحالية)."

    def add_arguments(self, parser):
        parser.add_argument("--source", type=Path, default=settings.PLANS_SOURCE_DB)

    def handle(self, *args, source: Path, **options):
        try:
            result = PlanImportService(source).run()
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"plans={result.plans} lessons={result.lessons} entries={result.entries} outcomes={result.outcomes}"
        ))
