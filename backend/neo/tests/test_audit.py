"""مدقق جودة الدروس: المحلّلات، والقواعد، والتسجيل؛ بلا منصة."""
from datetime import date
from pathlib import Path

from neo.domain.quality import LessonQuality
from neo.domain.types import ParsedLesson
from neo.infrastructure.parsers import parse_sections, parse_tiles
from neo.models import LessonAudit, SyncRun
from neo.services.audit_service import AuditService
from neo.services.scorecard_service import build
from neo.services.sync_service import SyncService

FIX = Path(__file__).parent / "fixtures"
LMS = 602598
TILES = (FIX / "lesson_tiles.html").read_text(encoding="utf-8")
SECTIONS = (FIX / "lesson_sections.html").read_text(encoding="utf-8")


def test_parse_tiles():
    tiles = {t.lms_lesson_id: t for t in parse_tiles(TILES)}
    assert tiles[16646488].image_default and tiles[16646488].sections == 1 and tiles[16646488].has_outcomes
    assert not tiles[17844979].image_default and tiles[17844979].sections == 6


def test_parse_sections():
    kinds = [(s.kind, s.title[:6]) for s in parse_sections(SECTIONS)]
    assert kinds == [("powerpoint", "العرض "), ("movieStrip", "فيديو "), ("sparkle", "قسم من"), ("quiz", "التقيي")]


def test_short_description_flagged():
    q = LessonQuality(False, "وصف قصير", ("عرض", "فيديو", "تقييم"), True)
    assert q.issues() == ["short_description"]


def test_quality_rules():
    good = LessonQuality(False, "ستتعلم أن تحل معادلات خطية بمجهول واحد باستخدام خصائص المساواة، وتتحقق من صحة الحل بالتعويض، وتفسر الناتج في سياق مسألة حياتية.", ("عرض", "فيديو", "تقييم"), True)
    assert good.issues() == [] and good.has_assessment
    bad = LessonQuality(True, "  ", ("عرض",), False)
    assert bad.issues() == ["generic_image", "no_description", "few_sections", "no_assessment", "no_outcomes"]


class Client:
    def __init__(self, lesson_pages):
        self.lesson_pages = lesson_pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def lesson_list_html(self, lms_id):
        return TILES

    def lesson_page_html(self, lms_id, lesson_id):
        return self.lesson_pages.get(lesson_id, "")

    def lesson_tags(self, lms_id, lesson_id):
        return ["كلمة"]

    quiz_counts = [5]

    def quiz_question_counts(self, lms_id, lesson_id):
        return self.quiz_counts


def test_audit_records_and_feeds_scorecard(classes):
    k = classes[LMS]
    SyncService().ingest(k, [
        ParsedLesson(16646488, 1, "تهيئة", "", date(2026, 8, 30), 3),
        ParsedLesson(17844979, 28, "حل المعادلات", "ستتعلم أن تحل معادلات خطية بمجهول واحد باستخدام خصائص المساواة، وتتحقق من صحة الحل بالتعويض، وتفسر الناتج في سياق مسألة حياتية.", date(2026, 11, 2), 1),
        ParsedLesson(99, 47, "ليس في القائمة", "", None, None),
    ], [])
    run = AuditService().run([k], lambda: Client({17844979: SECTIONS}))[0]
    assert run.kind == SyncRun.Kind.AUDIT and not run.ok  # درس محلي لم يظهر في القائمة
    assert run.summary["lessons"] == 2 and run.summary["complete"] == 1 and run.summary["not_in_list"] == [47]
    assert run.summary["issues"] == {"صورة عامة": 1, "بلا وصف": 1, "أقل من 3 أقسام": 1, "بلا تقييم": 1}
    first = LessonAudit.objects.get(lesson__lms_lesson_id=16646488)
    assert first.sections == [] and not first.complete
    good = LessonAudit.objects.get(lesson__lms_lesson_id=17844979)
    assert good.sections == ["عرض", "فيديو", "sparkle", "تقييم"] and good.complete
    content = next(c for c in build(date(2026, 11, 2))["criteria"] if c["key"] == "content")
    assert content["value"] == 50.0 and "مستوفٍ" in content["detail"]
    # إعادة التدقيق تحدّث ولا تكرر
    AuditService().run([k], lambda: Client({17844979: SECTIONS}))
    assert LessonAudit.objects.count() == 2


def test_few_questions_flagged():
    from neo.infrastructure.parsers import parse_question_count
    good = ("عرض", "فيديو", "تقييم")
    long = "ستتعلم أن تحل معادلات خطية بمجهول واحد باستخدام خصائص المساواة، وتتحقق من صحة الحل بالتعويض، وتفسر الناتج في سياق مسألة حياتية."
    assert LessonQuality(False, long, good, True, True, (4,)).issues() == ["few_questions"]
    assert LessonQuality(False, long, good, True, True, (5, 6)).issues() == []
    assert LessonQuality(False, long, good, True, True, ()).issues() == []  # لم يُقرأ: لا نقص مُختلق
    html = "".join(f'<a href="/quiz_question_bank/show_question/9?container_id=1&amp;position={i}">' for i in (1, 2, 2, 3))
    assert parse_question_count(html) == 3
