"""
python manage.py neo_prep --class 602728 --week 11   → حزمة التحضير الأسبوعية (قراءة فقط من المنصة)
    --dest PATH    مجلد الوجهة بدل سطح المكتب
    --no-word      بلا فتح Word للتحقق وتصدير PDF
الطرفية في ويندوز تشوّه العربية، فالتقرير الكامل يُكتب ملف UTF-8 ويُطبع مساره.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from neo.infrastructure.client import NeoClient, NotLoggedIn, PlatformError
from neo.models import SyncRun
from neo.services import pipeline
from neo.services.sync_service import NoActiveClasses


class Command(BaseCommand):
    help = "حزمة التحضير الأسبوعية لصف وأسبوع من الخطة."

    def add_arguments(self, parser):
        parser.add_argument("--class", dest="lms", type=int, required=True, metavar="LMS_ID")
        parser.add_argument("--week", type=int, required=True)
        parser.add_argument("--dest", default="")
        parser.add_argument("--no-word", action="store_true")
        parser.add_argument("--show-browser", action="store_true")

    def handle(self, *args, lms, week, dest, no_word, show_browser, **opts):
        policy = {k: v for k, v in (("dest_dir", dest), ("word_check", False if no_word else None)) if v is not None and v != ""}
        try:
            runs = pipeline.prep_pack(lms, week, lambda: NeoClient(headless=not show_browser), policy)
        except (NotLoggedIn, PlatformError, NoActiveClasses, pipeline.PipelineError) as exc:
            raise CommandError(str(exc)) from exc
        run = next(r for r in runs if r.kind == SyncRun.Kind.PREP)
        report = settings.NEO_PREP["cache_dir"] / "reports" / f"prep_{lms}_W{week:03d}_{run.pk}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(run.summary, ensure_ascii=False, indent=1), encoding="utf-8")
        write = self.style.SUCCESS if run.ok else self.style.ERROR
        self.stdout.write(write(f"prep #{run.pk} ok={run.ok} files={run.summary['files']} "
                                f"downloads={run.summary['downloads']} same_as_previous={run.summary['same_as_previous']}"))
        self.stdout.write(f"folder: {run.summary['folder']}")
        self.stdout.write(f"report: {report}")
