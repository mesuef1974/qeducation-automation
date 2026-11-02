"""طابور المهام والواجهة البرمجية للواجهة الأمامية؛ بلا منصة (عميل وهمي)."""
from datetime import date
from pathlib import Path

import pytest

from neo.domain.types import ParsedLesson
from neo.infrastructure.client import BrowserBusy, NotLoggedIn
from neo.models import Job, PublishProposal, SyncRun
from neo.services.job_service import JobService, session_state
from neo.services.pipeline import PipelineError
from neo.services.publish_service import PublishService
from neo.services.sync_service import SyncService

FIX = Path(__file__).parent / "fixtures"
LMS = 602598


class FakeClient:
    def __init__(self, fail=None):
        self.fail = fail

    def __enter__(self):
        if self.fail:
            raise self.fail
        return self

    def __exit__(self, *exc):
        return False

    def lesson_list_html(self, lms_id):
        return (FIX / "lesson_list.html").read_text(encoding="utf-8")

    def timetable_html(self, lms_id):
        return ""

    def student_view_html(self, lms_id):
        return (FIX / "student_lessons.html").read_text(encoding="utf-8")


def maker(fail=None):
    return lambda headless: (lambda: FakeClient(fail))


# ------------------------------------------------------------- الطابور

def test_enqueue_is_idempotent_while_active(classes):
    svc = JobService()
    a, created = svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})
    b, again = svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS], "approve": None})  # الفارغ يُهمل
    assert created and not again and a.pk == b.pk
    with pytest.raises(PipelineError):
        svc.enqueue(Job.Kind.VERIFY, {"run": 1})


def test_claim_one_at_a_time(classes):
    svc = JobService()
    first, _ = svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})
    svc.enqueue(Job.Kind.LOGIN)
    job = svc.claim()
    assert job.pk == first.pk and job.status == Job.Status.RUNNING
    assert svc.claim() is None  # مهمة قيد التشغيل تمنع غيرها
    assert svc.recover() == 1 and Job.objects.get(pk=first.pk).status == Job.Status.FAILED
    assert svc.claim().kind == Job.Kind.LOGIN


def test_run_verify_links_runs(classes):
    svc = JobService()
    job = svc.run(svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})[0], maker(), today=date(2026, 11, 2))
    assert job.status == Job.Status.DONE and job.error == ""
    assert sorted(job.runs.values_list("kind", flat=True)) == [SyncRun.Kind.FETCH, SyncRun.Kind.VERIFY]
    # بعد اكتمالها يمكن طلب المهمة نفسها من جديد
    assert svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})[1]


@pytest.mark.parametrize("exc, kind", [
    (NotLoggedIn("انتهت الجلسة"), Job.Error.SESSION),
    (BrowserBusy("مشغول"), Job.Error.BUSY),
    (RuntimeError("?"), Job.Error.UNEXPECTED),
])
def test_run_failure_is_classified(classes, exc, kind):
    svc = JobService()
    job = svc.run(svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})[0], maker(exc))
    assert job.status == Job.Status.FAILED and job.error_kind == kind
    assert session_state()["expired"] is (kind == Job.Error.SESSION)


def test_run_input_error(classes):
    svc = JobService()
    job = svc.run(svc.enqueue(Job.Kind.PUBLISH_APPLY, {"run": 999})[0], maker())
    assert job.error_kind == Job.Error.INPUT and "999" in job.error


def test_cancel_only_queued(classes):
    svc = JobService()
    job, _ = svc.enqueue(Job.Kind.LOGIN)
    assert svc.cancel(job) and not svc.cancel(job)


# ------------------------------------------------------------- الواجهة البرمجية

@pytest.fixture
def publish_run(classes):
    k = classes[LMS]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "ظاهر بلا نقاط", "", date(2026, 9, 15), 7),
        ParsedLesson(2, 2, "مخفي مؤرخ", "", date.today(), 6, hidden=True),
    ], [])
    return PublishService().plan(k)


def test_classes_overview(client, publish_run):
    data = client.get("/api/neo/classes/").json()
    k = next(c for c in data if c["lms_id"] == LMS)
    assert k["overview"]["lessons"]["total"] == 2 and k["overview"]["lessons"]["hidden"] == 1
    assert k["overview"]["review"]["publish"] == {"pending": 2, "approved": 0, "latest_run": publish_run.pk}
    assert [x["position"] for x in k["overview"]["today"]] == [2]
    assert client.get(f"/api/neo/classes/{LMS}/").json()["overview"]["lessons"]["total"] == 2


def test_lessons_filter(client, publish_run):
    assert [x["position"] for x in client.get(f"/api/neo/lessons/?class={LMS}&hidden=1").json()] == [2]
    assert client.get("/api/neo/lessons/?class=x").status_code == 400


def test_proposals_decide(client, publish_run):
    url = "/api/neo/proposals/publish/"
    items = client.get(f"{url}?run={publish_run.pk}&status=pending").json()
    assert len(items) == 2 and items[0]["lesson"]["title"]
    ids = [p["id"] for p in items]
    assert client.post(f"{url}decide/", {"ids": ids, "decision": "approve"}, "application/json").json() == {"changed": 2}
    # التكرار لا يغيّر شيئًا
    assert client.post(f"{url}decide/", {"ids": ids, "decision": "approve"}, "application/json").json() == {"changed": 0}
    assert PublishProposal.objects.filter(status=PublishProposal.Status.APPROVED).count() == 2
    assert client.post(f"{url}decide/", {"ids": [], "decision": "x"}, "application/json").status_code == 400
    assert client.get("/api/neo/proposals/nope/").status_code == 404


def test_jobs_api(client, classes):
    body = {"kind": "publish_apply", "params": {"run": 5, "approve": "all", "limit": 3}}
    r1 = client.post("/api/neo/jobs/", body, "application/json")
    r2 = client.post("/api/neo/jobs/", body, "application/json")
    assert (r1.status_code, r2.status_code) == (201, 200) and r1.json()["id"] == r2.json()["id"]
    assert r1.json()["status"] == "queued" and r1.json()["kind_label"]
    bad = [{"kind": "verify", "params": {"run": 1}}, {"kind": "sync_apply", "params": {}},
           {"kind": "assign_apply", "params": {"run": 1, "limit": 0}}, {"kind": "nope"}]
    assert {client.post("/api/neo/jobs/", b, "application/json").status_code for b in bad} == {400}
    jid = r1.json()["id"]
    assert client.post(f"/api/neo/jobs/{jid}/cancel/").json()["status"] == "failed"
    assert client.post(f"/api/neo/jobs/{jid}/cancel/").status_code == 400
    assert client.get("/api/neo/jobs/").json()["count"] == 1
    assert client.get("/api/neo/session/").json() == {"expired": False, "checked_at": None,
                                                      "worker_busy": False, "queued": 0}
