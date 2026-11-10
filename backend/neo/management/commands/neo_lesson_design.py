"""
python manage.py neo_lesson_design --name review_u2 --class 602598 --unit "الوحدة الثانية: ..." --date 2026-11-19 --period 1
يولّد مجلد المواصفة في .local/lessons/<name>/ ويطبع معاينته؛ بعد اعتماد المعلم:
python manage.py neo_lesson --spec .local/lessons/<name>/lesson.json --apply --queue
"""
from datetime import date
from pathlib import Path as Path_

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from neo.domain import lesson_spec
from neo.infrastructure.plan_docx import PlanTemplateError
from neo.models import PlatformClass
from neo.services import lesson_build_service as build
from neo.services import lesson_designer, pipeline
from neo.services.publish_service import policy


class Command(BaseCommand):
    help = "يصمّم درس مراجعة كاملًا (عرض وورقة عمل وخطة وتقييم) ويكتب مواصفته محليًا بلا لمس المنصة."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="اسم المجلد داخل .local/lessons")
        parser.add_argument("--class", dest="lms", required=True, type=int)
        parser.add_argument("--unit", required=True)
        parser.add_argument("--date", required=True)
        parser.add_argument("--period", required=True, type=int)
        parser.add_argument("--year", default="2026-2027")
        parser.add_argument("--grade", default="الصف العاشر")
        parser.add_argument("--term", default="الفصل الأول")
        parser.add_argument("--before", default="", help="عنوان الدرس الذي يُرتَّب هذا قبله")
        parser.add_argument("--title", default="")
        parser.add_argument("--prefix", default="10.2.", help="بادئة رموز نتاجات الوحدة للربط")
        parser.add_argument("--deck-template", type=Path_, default=None)
        parser.add_argument("--plan-template", type=Path_, default=None)
        parser.add_argument("--hidden", action="store_true", help="لا يُظهر الدرس بعد بنائه")

    def handle(self, *args, name, lms, unit, date: str, period, year, grade, term, before, title, prefix,
               deck_template, plan_template, hidden, **opts):
        if "/" in name or "\\" in name or name.startswith("."):
            raise CommandError("اسم المجلد بلا مسارات")
        klass = PlatformClass.objects.filter(lms_id=lms, active=True).first()
        if klass is None:
            raise CommandError(f"الصف {lms} غير مسجّل أو معطّل")
        p = policy(klass)
        points = {"points": p.points, "game": p.game, "notification": p.notification} if p.points > 0 else {}
        req = lesson_designer.ReviewRequest(
            lms, year, unit, date_of(date), period, grade, term, before, title, deck_template, plan_template,
            settings.NEO_PREP["cache_dir"], (prefix,), points, not hidden)
        try:
            path = lesson_designer.design(req, pipeline.lesson_dir() / name)
        except PlanTemplateError as exc:
            raise CommandError(str(exc)) from exc
        try:
            spec = lesson_spec.load(path)
        except lesson_spec.SpecError as exc:
            raise CommandError(str(exc)) from exc
        for line in build.describe(spec):
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(f"المواصفة: {path}"))
        self.stdout.write(self.style.WARNING("معاينة فقط: لم يُكتب شيء على المنصة."))


def date_of(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise CommandError("التاريخ بصيغة YYYY-MM-DD") from exc
