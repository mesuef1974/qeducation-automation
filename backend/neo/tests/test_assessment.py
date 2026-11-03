"""تقييم ذاتي التصحيح: صيغة الأسئلة النصية، وبنك الموضوع، واقتراحه وتطبيقه إضافةً فقط؛ بلا منصة."""
from datetime import date

import pytest
from django.utils import timezone

from neo.domain import assessment as a
from neo.domain import question_bank as qb
from neo.domain.types import ParsedLesson
from neo.models import LessonAudit, SyncRun
from neo.services.content_service import ContentService
from neo.services.sync_service import SyncService
from neo.tests.test_content import LMS, Client

QS = [a.Question(a.MCQ, "كم 2+2؟", ("4", "3", "5"), 0), a.Question(a.TF, "2 زوجي.", answer=True)]
TEXT = "س: كم 2+2؟\n* 4\n- 3\n- 5\n\nس: 2 زوجي.\n= صح"


def test_text_roundtrip():
    assert a.to_text(QS) == TEXT
    assert a.parse_text(TEXT) == QS
    assert a.from_dicts([q.as_dict() for q in QS]) == QS


@pytest.mark.parametrize("bad", ["- خيار بلا سؤال", "س: ناقص\n- أ\n- ب", "س: اثنان\n* أ\n* ب", "س: ص\n= ربما", "س: ع\n- أ\n= صح"])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        a.parse_text(bad)


def test_bank_by_topic_and_part():
    assert qb.topic_of("المميزات الأساسية للدالة التربيعية 2") == qb.topic_of("المميزات الاساسية للدالة التربيعيه")
    p1, p2 = qb.questions_for("المميزات الاساسية للدالة التربيعية 1"), qb.questions_for("المميزات الاساسية للدالة التربيعية 2")
    assert len(p1) == qb.PER_QUIZ and p1 != p2 and not set(p1) & set(p2)
    assert qb.questions_for("موضوع لا بنك له 1") == []
    for qs in qb.BANK.values():  # كل سؤال اختيار له إجابة صحيحة واحدة ضمن خياراته
        assert all(q.type == a.TF or 0 <= q.correct < len(q.choices) >= 2 for q in qs)


class QuizClient(Client):
    def __init__(self, has=False, **kw):
        super().__init__(**kw)
        self.has = has

    def assessment_names(self, lms_id, lesson_id):
        return ["تقييم آخر للمعلم"] if self.has else []

    def add_quiz(self, lms_id, lesson_id, name, questions):
        self.calls.append(("quiz", lesson_id, name, len(questions)))
        return 1


def _audited(classes, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    k = classes[LMS]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "المميزات الاساسية للدالة التربيعية 1", "وصف", date(2026, 9, 1), 1),
        ParsedLesson(2, 2, "موضوع بلا بنك", "وصف", date(2026, 9, 2), 1),
    ], [])
    now = timezone.now()
    for pos in (1, 2):
        LessonAudit.objects.create(lesson=k.lessons.get(position=pos), image_default=False, sections=["عرض"],
                                   has_outcomes=True, issues=["no_assessment"], audited_at=now)
    return k


def test_plan_proposes_quiz_only_with_bank(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    run = ContentService().plan([k], lambda: QuizClient())[0]
    assert run.summary["proposals"] == 1 and run.summary["by_kind"] == {"تقييم ذاتي التصحيح": 1, "بلا بنك أسئلة": 1}
    p = run.content_proposals.get()
    assert p.lesson.position == 1 and p.payload["name"].startswith("تقييم الدرس 1:")
    assert a.parse_text(p.payload["text"]) == a.from_dicts(p.payload["questions"])


def test_apply_quiz_adds_only(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    svc = ContentService()
    run = svc.plan([k], lambda: QuizClient())[0]
    svc.approve(run.pk)
    client = QuizClient(has=True)
    assert svc.apply(run, lambda: client).kind == SyncRun.Kind.CONTENT_APPLY
    assert client.calls == [] and run.content_proposals.get().status == "skipped"
    svc.approve(run.pk)
    run.content_proposals.update(status="approved")
    client = QuizClient()
    svc.apply(run, lambda: client)
    assert client.calls == [("quiz", 1, run.content_proposals.get().payload["name"], qb.PER_QUIZ)]
    assert run.content_proposals.get().status == "applied"
