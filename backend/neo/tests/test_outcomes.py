"""ربط نتاجات التعلم: تحليل نموذج الربط، واقتراح الربط لدرس بلا نتاجات فقط، وتطبيقه إضافةً خالصة؛ بلا منصة."""
from datetime import date

from django.utils import timezone

from neo.domain import question_bank as qb
from neo.domain.types import ParsedLesson
from neo.infrastructure.parsers import parse_available_outcomes
from neo.models import LessonAudit, SyncRun
from neo.services.content_service import ContentService
from neo.services.sync_service import SyncService
from neo.tests.test_content import LMS, Client

EDIT_HTML = """
<form action="/teacher_lesson/save_competencies/1?lesson_id=5" method="post">
<ul>
 <li><input type="checkbox" name="proficiencies[]" value="44992"><a href="/teacher_competency/show/1?proficiency_id=44992">10.2.2. يقدّر جذور المعادلة</a></li>
 <li><input type="checkbox" name="proficiencies[]" value="44997"><a href="/teacher_competency/show/1?proficiency_id=44997">10.3.1.   يستكشف مواقف</a></li>
 <li><input type="checkbox" name="proficiencies[]" value="44998"><a href="/teacher_competency/show/1?proficiency_id=44998">10.3.2. يحدّد خصائص</a></li>
</ul></form>"""
TITLE = "حل المعادلات التربيعية بيانيا 2"


def test_parse_available_outcomes():
    assert parse_available_outcomes(EDIT_HTML) == [
        {"id": 44992, "code": "10.2.2", "text": "يقدّر جذور المعادلة"},
        {"id": 44997, "code": "10.3.1", "text": "يستكشف مواقف"},
        {"id": 44998, "code": "10.3.2", "text": "يحدّد خصائص"},
    ]
    assert qb.outcomes_for(TITLE) == ("10.2.2", "10.3.1") and qb.outcomes_for("موضوع آخر") == ()


class OutcomeClient(Client):
    def __init__(self, linked=False, **kw):
        super().__init__(**kw)
        self.linked = linked

    def outcomes_html(self, lms_id, lesson_id):
        return '<div class="proficiencyItem"><a>10.3.2. نص</a></div>' if self.linked else "<div></div>"

    def available_outcomes(self, lms_id, lesson_id):
        self.calls.append(("available", lesson_id))
        return parse_available_outcomes(EDIT_HTML)

    def link_outcomes(self, lms_id, lesson_id, ids):
        self.calls.append(("link", lesson_id, ids))
        return [("10.2.2", "x"), ("10.3.1", "y")]


def _audited(classes, settings, tmp_path, titles):
    settings.MEDIA_ROOT = tmp_path
    k = classes[LMS]
    SyncService().ingest(k, [ParsedLesson(i, i, t, "وصف", date(2026, 9, i), 1) for i, t in enumerate(titles, 1)], [])
    for pl in k.lessons.all():
        LessonAudit.objects.create(lesson=pl, image_default=False, sections=["عرض", "صفحة"], has_outcomes=False,
                                   issues=["no_outcomes"], audited_at=timezone.now())
    return k


def test_plan_links_only_known_topics_without_outcomes(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path, [TITLE, "موضوع بلا رموز"])
    client = OutcomeClient()
    run = ContentService().plan([k], lambda: client)[0]
    assert client.calls == [("available", 1)]  # لا يُجلب نموذج الربط لدرس بلا رموز في البنك
    assert run.summary["by_kind"] == {"ربط نتاجات": 1, "بلا نتاجات في البنك": 1}
    p = run.content_proposals.get()
    assert [o["id"] for o in p.payload["outcomes"]] == [44992, 44997] and p.payload["text"].startswith("10.2.2 ")


def test_apply_links_then_skips_when_already_linked(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path, [TITLE])
    svc = ContentService()
    run = svc.plan([k], lambda: OutcomeClient())[0]
    svc.approve(run.pk)
    client = OutcomeClient()
    assert svc.apply(run, lambda: client).kind == SyncRun.Kind.CONTENT_APPLY
    assert client.calls == [("link", 1, [44992, 44997])] and run.content_proposals.get().status == "applied"
    run.content_proposals.update(status="approved")
    client = OutcomeClient(linked=True)
    svc.apply(run, lambda: client)
    assert client.calls == [] and run.content_proposals.get().status == "skipped"
