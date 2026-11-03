"""محرك المحتوى: المولّد النقي، واقتراح الإضافات من التدقيق، والتطبيق إضافةً فقط؛ بلا منصة."""
from datetime import date
from pathlib import Path

from django.utils import timezone

from neo.domain import content as gen
from neo.domain.types import ParsedLesson
from neo.infrastructure.client import NotLoggedIn
from neo.infrastructure.parsers import parse_outcomes
from neo.models import ContentProposal, LessonAudit, SyncRun
from neo.services.content_service import ContentService
from neo.services.sync_service import SyncService

LMS = 602598
OUTCOMES = """<span class="proficiencyItem"><a href="/x">10.3.1. يستكشف مواقف من الحياة اليومية.</a></span>
<span class="proficiencyItem"><a href="/y">10.3.2 يرسم التمثيل البياني.</a></span>"""


def test_parse_outcomes():
    assert parse_outcomes(OUTCOMES) == [("10.3.1", "يستكشف مواقف من الحياة اليومية."), ("10.3.2", "يرسم التمثيل البياني.")]


def test_generator_is_deterministic_and_rtl_safe():
    ctx = gen.LessonContext(3, "المميزات الأساسية", 1, "الدوال التربيعية", (("10.3.1", "يستكشف"),), "درس سابق", ("كتاب الطالب",))
    d = gen.description(ctx)
    assert d.startswith("في هذا الدرس ستتعلم أن:\n• يستكشف") and "الوحدة 1: الدوال التربيعية" in d and "درس سابق" in d
    html = gen.intro_section_html(ctx)
    assert "<h3>أهداف الدرس</h3>" in html and "كتاب الطالب" in html and "10.3.1" in html
    assert gen.tile_spec(ctx) == {"color": gen.UNIT_COLORS[1], "number": 3, "title": "المميزات الأساسية",
                                  "unit": "الوحدة 1: الدوال التربيعية", "motif": "features"}
    assert gen.motif_of("حل المعادلات التربيعية بيانيا 2") == "roots" and gen.motif_of("تهيئة") == "parabola"
    assert gen.description(gen.LessonContext(1, "تهيئة", None, "")) == "في هذا الدرس ستتعلم أن:\n• تهيئة"


class Client:
    def __init__(self, fail=None, description="", default_tile=True, names=()):
        self.fail, self.description, self.default_tile, self.names = fail, description, default_tile, list(names)
        self.calls = []

    def __enter__(self):
        if self.fail:
            raise self.fail
        return self

    def __exit__(self, *exc):
        return False

    def outcomes_html(self, lms_id, lesson_id):
        return OUTCOMES if lesson_id == 1 else ""

    def lesson_description(self, lms_id, lesson_id):
        return self.description

    def set_lesson_description(self, lms_id, lesson_id, text):
        self.calls.append(("description", lesson_id, text[:12]))

    def section_names(self, lms_id, lesson_id):
        return self.names

    def add_page_section(self, lms_id, lesson_id, name, html):
        self.calls.append(("section", lesson_id, name))

    def tile_is_default(self, lms_id, lesson_id):
        return self.default_tile

    def set_tile_picture(self, lms_id, lesson_id, png, color):
        assert Path(png).exists()
        self.calls.append(("image", lesson_id, color))


def _audited(classes, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    k = classes[LMS]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "ناقص كله", "", date(2026, 9, 1), 1),
        ParsedLesson(2, 2, "ناقص الصورة فقط", "له وصف", date(2026, 9, 2), 1),
        ParsedLesson(3, 3, "مستوفٍ", "وصف", date(2026, 9, 3), 1),
    ], [])
    now = timezone.now()
    for pos, issues in ((1, ["generic_image", "no_description", "few_sections", "no_assessment"]),
                        (2, ["generic_image"]), (3, [])):
        LessonAudit.objects.create(lesson=k.lessons.get(position=pos), image_default="generic_image" in issues,
                                   sections=[], has_outcomes=True, issues=issues, audited_at=now)
    return k


def test_plan_proposes_only_missing(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    run = ContentService().plan([k], lambda: Client())[0]
    assert run.kind == SyncRun.Kind.CONTENT_PLAN and run.ok
    assert run.summary["proposals"] == 4 and run.summary["without_outcomes"] == [2]
    kinds = sorted((p.lesson.position, p.kind) for p in run.content_proposals.all())
    assert kinds == [(1, "description"), (1, "image"), (1, "section"), (2, "image")]
    desc = run.content_proposals.get(kind="description")
    assert "يستكشف مواقف" in desc.payload["text"]
    image = run.content_proposals.get(lesson__position=2)
    assert (tmp_path / image.payload["file"]).exists() and image.payload["color"]
    # اقتراح أحدث يستبدل المعلّق
    again = ContentService().plan([k], lambda: Client())[0]
    assert run.content_proposals.filter(status="rejected").count() == 4 and again.content_proposals.count() == 4


def test_apply_one_lesson_adds_only(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    svc = ContentService()
    run = svc.plan([k], lambda: Client())[0]
    assert svc.approve(run.pk) == 4
    client = Client(description="كُتب يدويًا بعد الاقتراح")  # الحالة على المنصة تغيّرت: لا نكتب فوقها
    out = svc.apply(run, lambda: client, lesson=1)
    assert out.kind == SyncRun.Kind.CONTENT_APPLY and out.ok
    assert client.calls == [("image", 1, gen.UNIT_COLORS[0]), ("section", 1, gen.INTRO_SECTION)]
    by = {p.kind: p for p in run.content_proposals.filter(lesson__position=1)}
    assert by["description"].status == "skipped" and by["image"].status == "applied" and by["section"].status == "applied"
    assert run.content_proposals.get(lesson__position=2).status == "approved"  # درس آخر لم يُمس


def test_apply_session_loss_keeps_progress(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    svc = ContentService()
    run = svc.plan([k], lambda: Client())[0]
    svc.approve(run.pk, lesson=2)
    try:
        svc.apply(run, lambda: Client(fail=NotLoggedIn("x")))
    except NotLoggedIn:
        pass
    assert run.content_proposals.get(lesson__position=2).status == "approved"
    assert ContentProposal.objects.filter(status="applied").count() == 0
