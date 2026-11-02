from datetime import date
from pathlib import Path

import pytest

from neo.domain.types import ParsedLesson
from neo.infrastructure.client import NotLoggedIn
from neo.infrastructure.parsers import (
    parse_default_visibility,
    parse_lessons,
    parse_points_actions,
    parse_points_games,
)
from neo.models import PlatformLesson, PublishProposal
from neo.services.publish_service import ALREADY, PublishService, policy
from neo.services.sync_service import SyncService

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_badges():
    lessons = parse_lessons(read("lesson_tiles.html"), "2026-2027")
    # ظاهر ويمنح النقاط | ظاهر بلا نقاط | مخفي «شخصى» بلا نقاط
    assert [(p.position, p.hidden, p.awards_points) for p in lessons] == [
        (1, False, True), (15, False, False), (28, True, False)]


def test_parse_visibility_and_points():
    assert parse_default_visibility(read("lesson_shown_hidden.html")) is False
    assert parse_default_visibility(read("lesson_shown_visible.html")) is True
    assert parse_default_visibility("<p></p>") is None
    assert parse_points_actions(read("lesson_completion_none.html")) == 0
    assert parse_points_actions(read("lesson_completion_points.html")) == 1


@pytest.fixture
def setup(classes):
    k = classes[602598]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "قديم", "", date(2026, 8, 30), 3, hidden=False, awards_points=True),
        ParsedLesson(2, 2, "ظاهر بلا نقاط", "", date(2026, 9, 15), 7),
        ParsedLesson(3, 3, "مخفي مؤرخ", "", date(2026, 11, 2), 6, hidden=True),
        ParsedLesson(4, 4, "مخفي بلا تاريخ", "", None, None, hidden=True, awards_points=True),
    ], [])
    return PublishService(), k


def test_plan(setup):
    svc, k = setup
    run = svc.plan(k)
    props = {p.lesson.lms_lesson_id: (p.show, p.add_points) for p in run.publish_proposals.select_related("lesson")}
    assert props == {2: (False, True), 3: (True, True)}
    assert run.summary["hidden_undated"] == [4] and run.summary["show"] == 1 and run.summary["add_points"] == 2
    # اقتراح أحدث يستبدل المعلّق
    svc.plan(k)
    assert PublishProposal.objects.filter(run=run, status=PublishProposal.Status.REJECTED).count() == 2


class FakeClient:
    """يحاكي المنصة: {lesson_id: [ظاهر، عدد إجراءات النقاط]}."""

    def __init__(self, state, broken=(), expire_at=None, games=("نجوم الرياضيات",)):
        self.state, self.broken, self.expire_at, self.writes = state, set(broken), expire_at, []
        self.games = list(games)

    def points_games(self, lms_id, lid):
        return self.games

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def lesson_shown(self, lms_id, lid):
        if lid == self.expire_at:
            raise NotLoggedIn("انتهت الجلسة")
        return self.state[lid][0]

    def show_lesson(self, lms_id, lid):
        self.writes.append(("show", lid))
        if lid not in self.broken:
            self.state[lid][0] = True

    def lesson_points_actions(self, lms_id, lid):
        return self.state[lid][1]

    def add_points_action(self, lms_id, lid, points, game, notification):
        self.writes.append(("points", lid, points, game, notification))
        self.state[lid][1] += 1


def test_apply_idempotent(setup):
    svc, k = setup
    run = svc.plan(k)
    svc.approve(run.pk)
    # الدرس 2 أُضيفت نقاطه يدويًا على المنصة بعد الاقتراح
    fake = FakeClient({2: [True, 1], 3: [False, 0]})
    log = svc.apply(run, lambda: fake)
    assert fake.writes == [("show", 3), ("points", 3, 5, "نجوم الرياضيات", "Popup")]
    st = {p.lesson.lms_lesson_id: (p.status, p.error) for p in run.publish_proposals.select_related("lesson")}
    assert st == {2: (PublishProposal.Status.SKIPPED, ALREADY), 3: (PublishProposal.Status.APPLIED, "")}
    assert log.ok and log.summary["applied"] == 1
    lesson = PlatformLesson.objects.get(lms_lesson_id=3)
    assert (lesson.hidden, lesson.awards_points) == (False, True)

    # إعادة التطبيق لا تكتب شيئًا
    run2 = svc.plan(k)
    assert not run2.publish_proposals.exists()


def test_apply_failure_and_session(setup):
    svc, k = setup
    run = svc.plan(k)
    svc.approve(run.pk)
    fake = FakeClient({2: [True, 0], 3: [False, 0]}, broken={3})
    log = svc.apply(run, lambda: fake)
    st = {p.lesson.lms_lesson_id: p.status for p in run.publish_proposals.select_related("lesson")}
    assert st == {2: PublishProposal.Status.APPLIED, 3: PublishProposal.Status.FAILED} and not log.ok

    run = svc.plan(k)
    svc.approve(run.pk)
    with pytest.raises(NotLoggedIn):
        svc.apply(run, lambda: FakeClient({3: [False, 0]}, expire_at=3))
    assert run.publish_proposals.get().status == PublishProposal.Status.APPROVED


def test_parse_points_games():
    html = """<form><select name="rule_action[arg2_id]"><option value="">تحديد</option>
      <option value="263104">تحدي التحمل</option><option value="442577">نجوم الرياضيات</option></select></form>"""
    assert parse_points_games(html) == ["تحدي التحمل", "نجوم الرياضيات"]


def test_class_policy_override(setup):
    _, k = setup
    assert (policy(k).game, policy(k).points) == ("نجوم الرياضيات", 5)
    k.points_game, k.points = "نجوم العلوم", 3
    assert (policy(k).game, policy(k).points) == ("نجوم العلوم", 3)
    k.points = 0
    assert policy(k).points == 0


def test_plan_game_missing(setup):
    svc, k = setup
    run = svc.plan(k, games=["تحدي التحمل"])
    assert not run.ok and "غير موجودة" in run.summary["points_error"]
    # الإظهار يبقى مقترحًا، والنقاط لا
    assert [(p.lesson.lms_lesson_id, p.show, p.add_points) for p in run.publish_proposals.all()] == [(3, True, False)]


def test_apply_game_missing(setup):
    svc, k = setup
    run = svc.plan(k)
    svc.approve(run.pk)
    fake = FakeClient({2: [True, 0], 3: [False, 0]}, games=["تحدي التحمل"])
    svc.apply(run, lambda: fake)
    assert fake.writes == [("show", 3)]
    assert {p.status for p in run.publish_proposals.all()} == {PublishProposal.Status.FAILED}


def test_fetch_visibility_from_tab(setup):
    svc, k = setup
    # الشارة قالت «مخفي» للدرس 3، والتبويب «ظاهر»؛ والدرس 2 عكسه
    games = svc.fetch([k], lambda: FakeClient({1: [True, 1], 2: [False, 0], 3: [True, 0], 5: [True, 0]}))
    hidden = dict(PlatformLesson.objects.filter(klass=k).values_list("lms_lesson_id", "hidden"))
    assert hidden == {1: False, 2: True, 3: False, 4: True} and games[k.pk] == ["نجوم الرياضيات"]
    # إعادة جلب القائمة لا تعيد «hidden» إلى قيمة الشارة
    SyncService().ingest(k, [ParsedLesson(3, 3, "مخفي مؤرخ", "", date(2026, 11, 2), 6, hidden=True)], [])
    assert PlatformLesson.objects.get(lms_lesson_id=3).hidden is False
