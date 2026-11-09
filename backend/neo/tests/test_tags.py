"""الكلمات الدلالية: المولّد النقي، والمحلل، والكشف في التدقيق، والاقتراح، والتطبيق إضافةً خالصةً؛ بلا منصة."""
from datetime import date

from django.utils import timezone

from neo.domain import keywords
from neo.domain.quality import LessonQuality
from neo.domain.types import ParsedLesson
from neo.infrastructure.parsers import parse_tags
from neo.models import ContentProposal, LessonAudit
from neo.services.content_service import ContentService
from neo.services.sync_service import SyncService
from neo.tests.helpers import confirm_matches
from neo.tests.test_content import LMS, Client

Kind = ContentProposal.Kind


def test_build_keywords_from_title_unit_and_codes():
    assert keywords.build("2.1 حل أنظمة المعادلات", "المعادلات، والمتباينات", ["10.2.4", "12A.3.5"]) == [
        "حل أنظمة المعادلات", "المعادلات والمتباينات", "10.2.4", "12A.3.5"]
    assert keywords.build("درس", "درس", []) == ["درس"]
    assert all("," not in t and "،" not in t for t in keywords.build("أ، ب", "ج,د", []))
    assert keywords.parse_text("المشتقات، الاشتقاق\n12A.3.5, المشتقات") == ["المشتقات", "الاشتقاق", "12A.3.5"]


def test_parse_tags():
    assert parse_tags("<div>لا يوجد</div>") == []
    assert parse_tags('<span class="tm-tag"><span>جذور</span><a>×</a></span><span class="tm-tag"><span>10.2.4</span></span>') \
        == ["جذور", "10.2.4"]
    assert parse_tags("<div>جذور، 10.2.4</div>") == ["جذور", "10.2.4"]


def test_quality_flags_missing_tags_only_when_known():
    assert "no_tags" in LessonQuality(False, "و", ("عرض", "صفحة", "تقييم"), True, False).issues()
    assert LessonQuality(False, "و", ("عرض", "صفحة", "تقييم"), True).issues() == []


class TagClient(Client):
    def __init__(self, tags=(), **kw):
        super().__init__(**kw)
        self.tags = list(tags)

    def lesson_tags(self, lms_id, lesson_id):
        return self.tags

    def set_lesson_tags(self, lms_id, lesson_id, tags):
        self.calls.append(("tags", lesson_id, tags))


def _audited(classes, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    k = classes[LMS]
    SyncService().ingest(k, [ParsedLesson(1, 1, "حل المعادلات التربيعية بيانيا 2", "وصف", date(2026, 9, 1), 1)], [])
    confirm_matches(k)
    for pl in k.lessons.all():
        LessonAudit.objects.create(lesson=pl, image_default=False, sections=["عرض", "صفحة", "تقييم"],
                                   has_outcomes=True, has_tags=False, issues=["no_tags"], audited_at=timezone.now())
    return k


def test_plan_proposes_tags_and_apply_is_add_only(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    run = ContentService().record_plan(k, list(k.lessons.all()), {1: [("10.3.1", "يستكشف")]})
    prop = run.content_proposals.get()
    assert prop.kind == Kind.TAGS and prop.payload["tags"][0] == "حل المعادلات التربيعية بيانيا 2"
    assert "10.3.1" in prop.payload["tags"]
    ContentService().approve(run.pk)
    client = TagClient()
    ContentService().apply(run, lambda: client)
    assert client.calls == [("tags", 1, prop.payload["tags"])]
    prop.refresh_from_db()
    assert prop.status == ContentProposal.Status.APPLIED


def test_apply_skips_lesson_that_already_has_tags(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    run = ContentService().record_plan(k, list(k.lessons.all()), {})
    ContentService().approve(run.pk)
    client = TagClient(tags=["موجودة"])
    ContentService().apply(run, lambda: client)
    assert client.calls == []
    assert run.content_proposals.get().status == ContentProposal.Status.SKIPPED
