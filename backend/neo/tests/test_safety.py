"""صمّامات الكتابة (docs/automation_criteria.md: الخطوات 1 و4 و5 والإيقاف الآلي)؛ بلا منصة."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from neo.domain.types import ParsedLesson
from neo.infrastructure.client import PlatformError, stamp
from neo.models import Job, PlatformClass, PlatformLesson, PublishProposal
from neo.services import pipeline, safety, weekly_service
from neo.services.job_service import _classify, session_state
from neo.services.publish_service import PublishService
from neo.services.sync_service import SyncService, lessons_problem
from neo.tests.helpers import confirm_matches

LMS = 602598
TODAY = date(2026, 11, 5)


@pytest.fixture
def lessons(classes):
    k = classes[LMS]
    SyncService().ingest(k, [ParsedLesson(i, i, f"درس {i}", "", date(2026, 11, 6), 1, hidden=True)
                             for i in (1, 2, 3)], [])
    confirm_matches(k)
    return k


def _unsure(pl: PlatformLesson) -> None:
    PlatformLesson.objects.filter(pk=pl.pk).update(override_code="", match_code="1.1", match_score=0.8,
                                                   confirmed_code="")


def test_stamp():
    assert stamp("2026-11-05") == (2026, 11, 5)
    assert stamp("2026-11-05 07:00") == stamp("2026-11-05 07:00:00") == (2026, 11, 5, 7, 0)
    assert stamp("") is None and stamp(None) is None


def test_halt_resume_and_classify(db):
    safety.require_writes_allowed()  # مفعّلة افتراضًا
    safety.halt("سبب أول")
    safety.halt("سبب ثانٍ")  # السبب الأول يبقى حتى إعادة التفعيل
    with pytest.raises(safety.WritesHalted, match="سبب أول"):
        safety.require_writes_allowed()
    assert _classify(safety.WritesHalted("x")) == Job.Error.HALTED
    assert session_state()["halted"] is True
    safety.resume()
    safety.require_writes_allowed()
    assert session_state()["halted"] is False


def test_two_failed_verifications_in_a_row_halt(db):
    safety.record_verify(False)
    safety.record_verify(True)  # النجاح يصفّر العدّاد
    safety.record_verify(False)
    assert not safety.state().halted
    safety.record_verify(False)
    assert safety.state().halted and "مرات متتالية" in safety.state().reason


def test_halted_stops_cycle_and_every_write(lessons):
    safety.halt("اختبار")
    assert weekly_service.due_cycle(datetime(2026, 11, 5, 14, tzinfo=ZoneInfo("Asia/Qatar"))) is None
    with pytest.raises(safety.WritesHalted):
        weekly_service.run([lessons], None, TODAY, {})
    svc = PublishService()
    run = svc.plan(lessons)
    svc.approve(run.pk)
    with pytest.raises(safety.WritesHalted):
        pipeline.publish_apply(run.pk, None, TODAY)
    assert run.publish_proposals.filter(status="approved").count() == 3  # لم يُمس شيء


def test_unsure_lesson_is_neither_proposed_nor_approved(lessons):
    svc = PublishService()
    run = svc.plan(lessons)
    pl1, pl2 = (PlatformLesson.objects.get(klass=lessons, position=n) for n in (1, 2))
    _unsure(pl2)
    assert svc.approve(run.pk) == 2  # الدرس 2 صار غير مؤكد بعد الاقتراح: لا يُعتمد
    _unsure(pl1)
    run = svc.plan(lessons)
    assert set(run.publish_proposals.values_list("lesson__position", flat=True)) == {3}
    assert [x[:3] for x in run.summary["unconfirmed_match"]] == ["1. ", "2. "]


def test_approval_expires_after_48h_or_when_lesson_changes(lessons):
    svc = PublishService()
    run = svc.plan(lessons)
    assert svc.approve(run.pk) == 3
    p1, p2, p3 = run.publish_proposals.order_by("lesson__position")
    assert p1.approved_at and p1.approved_fp
    PublishProposal.objects.filter(pk=p1.pk).update(approved_at=timezone.now() - timedelta(hours=49))
    PlatformLesson.objects.filter(pk=p2.lesson_id).update(title="عنوان تغيّر على المنصة")
    reasons = safety.check_approvals(run.publish_proposals.all())
    st = {p.pk: (p.status, p.error) for p in run.publish_proposals.all()}
    assert st[p1.pk][0] == "pending" and "48" in st[p1.pk][1]
    assert st[p2.pk][0] == "pending" and "تغيّر الدرس" in st[p2.pk][1]
    assert st[p3.pk][0] == "approved" and len(reasons) == 2


def test_guard_refetches_stale_sync_and_refuses_expired(lessons, monkeypatch):
    """لا كتابة على مزامنة أقدم من ساعة: يُجلب الصف من جديد؛ وما سقط اعتماده لا يُطبَّق ويُذكر سببه."""
    svc = PublishService()
    run = svc.plan(lessons)
    svc.approve(run.pk)
    PlatformClass.objects.filter(pk=lessons.pk).update(last_fetched_at=timezone.now() - timedelta(hours=2))
    fetched = []
    monkeypatch.setattr(pipeline.SyncService, "fetch",
                        lambda self, classes, factory: fetched.append([k.pk for k in classes]) or [])
    PublishProposal.objects.filter(run=run).update(approved_at=timezone.now() - timedelta(hours=49))
    with pytest.raises(pipeline.PipelineError, match="48"):
        pipeline.publish_apply(run.pk, None, TODAY)
    assert fetched == [[lessons.pk]]
    assert not run.publish_proposals.filter(status="approved").exists()


def test_lessons_problem():
    ok = [ParsedLesson(1, 1, "أ", "", None, None), ParsedLesson(2, 2, "ب", "", None, None)]
    assert lessons_problem(ok) == ""
    assert "الموضع" in lessons_problem([*ok, ParsedLesson(3, 2, "ج", "", None, None)])
    assert "المعرّف" in lessons_problem([*ok, ParsedLesson(2, 3, "ج", "", None, None)])
    assert "عنوان" in lessons_problem([ParsedLesson(4, 1, " ", "", None, None)])


class _ListClient:
    def __init__(self, ids):
        self.ids = ids

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def lesson_list_html(self, lms_id):
        tiles = "".join(f'<div class="draggable" id="{i}"><h2 class="class_name">{i}. درس {i}</h2></div>'
                        for i in self.ids)
        return f'<div id="blockView">{tiles}</div>'

    def timetable_html(self, lms_id):
        return ""


def test_fetch_refuses_any_shrink_until_confirmed_once(classes):
    k = classes[LMS]
    SyncService().ingest(k, [ParsedLesson(i, i, f"درس {i}", "", None, None) for i in (1, 2, 3)], [])
    with pytest.raises(PlatformError, match="نقص"):
        SyncService().fetch([k], lambda: _ListClient([1, 2]))
    k.refresh_from_db()
    assert PlatformLesson.objects.filter(klass=k).count() == 3
    assert (k.shrink_pending["saved"], k.shrink_pending["platform"], k.shrink_pending["missing"]) == (3, 2, ["3. درس 3"])
    k.allow_shrink = True  # المعلم أكّد الحذف مرة واحدة
    k.save()
    SyncService().fetch([k], lambda: _ListClient([1, 2]))
    k.refresh_from_db()
    assert PlatformLesson.objects.filter(klass=k).count() == 2 and not k.allow_shrink and k.shrink_pending == {}
    with pytest.raises(PlatformError, match="نقص"):  # التأكيد لمرة واحدة فقط
        SyncService().fetch([k], lambda: _ListClient([1]))


def test_api_safety_confirm_and_shrink(client, lessons):
    safety.halt("اختبار")
    assert client.get("/api/neo/safety/").json()["halted"] is True
    r = client.post("/api/neo/safety/", {"action": "resume"}, content_type="application/json")
    assert r.status_code == 200 and r.json()["halted"] is False and not safety.state().halted
    pl = PlatformLesson.objects.get(klass=lessons, position=1)
    _unsure(pl)
    r = client.post("/api/neo/lessons/confirm/", {"ids": [pl.lms_lesson_id]}, content_type="application/json")
    assert r.json() == {"changed": 1}
    pl.refresh_from_db()
    assert pl.confirmed_code == "1.1" and pl.match_sure
    assert client.post(f"/api/neo/classes/{LMS}/accept-shrink/").status_code == 400  # لا نقص بانتظار التأكيد
    PlatformClass.objects.filter(pk=lessons.pk).update(shrink_pending={"saved": 3, "platform": 2})
    assert client.post(f"/api/neo/classes/{LMS}/accept-shrink/").status_code == 200
    assert PlatformClass.objects.get(pk=lessons.pk).allow_shrink
