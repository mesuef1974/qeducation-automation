"""طابور المهام والواجهة البرمجية للواجهة الأمامية؛ بلا منصة (عميل وهمي)."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from neo.domain.types import ParsedLesson
from neo.infrastructure.client import BrowserBusy, NotLoggedIn
from neo.models import Job, PublishProposal, SyncRun, WorkerHeartbeat
from neo.services.job_service import ALIVE_S, JobService, beat, session_state, stop_beat
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


def test_worker_heartbeat(classes):
    svc = JobService()
    svc.enqueue(Job.Kind.LOGIN)
    svc.claim()  # «قيد التشغيل» بلا عامل حي: لا تُعدّ الواجهة العامل مشغولًا
    assert session_state()["worker_alive"] is False and session_state()["worker_busy"] is False
    beat(123)
    assert session_state()["worker_alive"] is True and session_state()["worker_busy"] is True
    WorkerHeartbeat.objects.update(seen_at=timezone.now() - timedelta(seconds=ALIVE_S + 1))
    assert session_state()["worker_alive"] is False
    beat(123)
    stop_beat()
    assert session_state()["worker_alive"] is False


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
    assert client.get("/api/neo/session/").json() == {"expired": False, "checked_at": None, "worker_alive": False,
                                                      "worker_busy": False, "queued": 0}


# ------------------------------------------------------------- خدمة الواجهة المبنية على /app/

def test_spa(db, client, settings, tmp_path):
    settings.FRONTEND_DIST = tmp_path
    assert client.get("/app/").status_code == 503  # لم تُبنَ بعد
    (tmp_path / "index.html").write_text("<div id=app>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.js").write_text("1", encoding="utf-8")
    assert client.get("/app/review/publish").content == b"<div id=app>"  # مسارات Vue تعيد الصفحة
    static = client.get("/app/assets/a.js")
    assert b"".join(static.streaming_content) == b"1"
    static.close()
    assert client.get("/app/..%2F..%2Fmanage.py").status_code == 404  # لا خروج من المجلد


def test_docs(db, client):
    r = client.get("/docs/report/platform_report.html")
    assert r.status_code == 200 and r["X-Frame-Options"] == "SAMEORIGIN"  # يُعرض في إطار الواجهة فقط
    r.close()
    assert client.get("/docs/automation_tasks.md").status_code == 404  # صفحات الويب فقط
    assert client.get("/docs/..%2Fbackend%2Fmanage.py").status_code == 404


def test_session_survives_recover(classes):
    """توقف العامل المفاجئ لا يخفي انتهاء الجلسة."""
    svc = JobService()
    svc.run(svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})[0], maker(NotLoggedIn("x")))
    svc.enqueue(Job.Kind.LOGIN)
    svc.claim()
    assert svc.recover() == 1
    assert session_state()["expired"] is True


# ------------------------------------------------------------- بطاقة الأداء

def test_scorecard(client, publish_run):
    data = client.get("/api/neo/scorecard/").json()
    crit = {c["key"]: c for c in data["current"]["criteria"]}
    assert len(crit) == 8 and data["baseline"] is None
    assert crit["engagement"]["measured"] is False and crit["compliance"]["value"] == 100
    assert crit["content"]["value"] == 0  # درسان بلا وصف
    assert client.post("/api/neo/scorecard/").status_code == 201
    assert client.post("/api/neo/scorecard/").status_code == 200  # لقطة واحدة لليوم
    data = client.get("/api/neo/scorecard/").json()
    assert data["baseline"]["day"] == data["current"]["day"] and len(data["series"]) == 1


def test_prep_pack_job_api(client, classes):
    ok = client.post("/api/neo/jobs/", {"kind": "prep_pack", "params": {"class": 602728, "week": 11}},
                     "application/json")
    assert ok.status_code == 201 and ok.json()["kind_label"] == "حزمة التحضير الأسبوعية"
    bad = [{"kind": "prep_pack", "params": {"class": 602728}}, {"kind": "prep_pack", "params": {"week": 11}},
           {"kind": "prep_pack", "params": {"class": 602728, "week": "11"}},
           {"kind": "prep_pack", "params": {"class": 602728, "week": 11, "run": 1}}]
    assert {client.post("/api/neo/jobs/", b, "application/json").status_code for b in bad} == {400}


def test_live_feed(client, classes):
    """تبويب «مباشر»: أحداث المهمة الجارية بعد رقم تسلسلي، وملخصها، والطابور، وآخر المهام."""
    from neo.services import live
    from neo.services.job_service import JobService, beat

    assert client.get("/api/neo/live/").json()["job"] is None
    svc = JobService()
    job, _ = svc.enqueue(Job.Kind.PREP_PACK, {"class": 602728, "week": 11})
    queued, _ = svc.enqueue(Job.Kind.VERIFY, {"classes": [602598]})
    job = svc.claim()
    beat(4321)
    live.start(job.pk, job.get_kind_display())
    live.stage("قراءة الملاحظات والأقسام وتنزيل الملفات", "prep")
    live.step("الدرس 49", 1, 6)
    live.emit("net", live.page_label("/teacher_lesson/notes/602728?lesson_id=1"), status=200)
    live.emit("file", "نُزّل: خطة درس", size=10)
    data = client.get("/api/neo/live/").json()
    assert data["worker"] == {"alive": True, "pid": 4321, "seen_at": data["worker"]["seen_at"]}
    assert data["job"]["id"] == job.pk and data["job"]["target"] == "الرياضيات 12/2 · الأسبوع 11"
    assert [e["kind"] for e in data["events"]] == ["start", "stage", "step", "net", "file"]
    assert data["events"][3]["text"] == "ملاحظات المعلم" and data["events"][3]["stage"].startswith("قراءة")
    # عقدة الرسم: تُضبط مع المرحلة وتلحق كل ما بعدها
    assert "node" not in data["events"][0] and {e["node"] for e in data["events"][1:]} == {"prep"}
    summ = data["job"]["live"]
    assert summ["nodes"] == ["prep"] and summ["stages"][0]["node"] == "prep"
    assert summ["progress"] == {"text": "الدرس 49", "current": 1, "total": 6, "stage": summ["stages"][0]["text"]}
    assert summ["counts"]["net"] == 1 and summ["last_seq"] == 5 and summ["end"] is None
    assert [q["id"] for q in data["queue"]] == [queued.pk] and data["queue"][0]["target"] == "الرياضيات 10/3"
    more = client.get("/api/neo/live/?since=5").json()
    assert more["events"] == []
    live.end("done", "تمت")
    assert client.get("/api/neo/live/?since=5").json()["events"][0]["kind"] == "end"
    live.emit("step", "بعد النهاية لا يُكتب")  # خارج مهمة: لا شيء
    assert client.get(f"/api/neo/live/?job={job.pk}").json()["job"]["live"]["last_seq"] == 6


def test_live_nodes_follow_stages(tmp_path):
    """المهمة تمر بعقد الرسم بترتيبها (جلب ← تحقق)، والعقدة غير المعروفة لا تغيّر الحالية."""
    from neo.services import live
    live.start(999, "تحقق")
    live.stage("جلب الدروس والجدول من المنصة", "fetch")
    live.emit("net", "قائمة الدروس", status=200)
    live.stage("التحقق من منظور الطالب", "verify")
    live.step("عرض 12/2 كطالب عام", 1, 1, node="nowhere")
    live.end("done", "تمت")
    events = live.read(999)
    assert [e.get("node") for e in events] == [None, "fetch", "fetch", "verify", "verify", "verify"]
    assert live.summary(999)["nodes"] == ["fetch", "verify"]


def test_live_marks_writes():
    """البث يعرض صفحة واحدة لكل تنقّل، ويَسِم الكتابة بطريقة الطلب الذي حوّل إليها."""
    from types import SimpleNamespace as NS

    from neo.infrastructure.client import BASE_URL, NeoClient
    from neo.services import live

    def resp(path, status=200, method="GET", came_from=None):
        req = NS(resource_type="document", method=method, redirected_from=came_from)
        return NS(request=req, url=BASE_URL + path, status=status)

    live.start(998, "تطبيق")
    post = NS(resource_type="document", method="POST", redirected_from=None)
    NeoClient._on_response(resp("/teacher_lesson/save/1", status=302, method="POST"))  # التحويل لا يظهر
    NeoClient._on_response(resp("/teacher_lesson/show/1?lesson_id=2", came_from=post))
    NeoClient._on_response(resp("/teacher_lessons/list/602728"))
    NeoClient._on_response(NS(request=NS(resource_type="image", method="GET", redirected_from=None),
                              url=BASE_URL + "/x.png", status=200))
    live.end("done", "تمت")
    net = [e for e in live.read(998) if e["kind"] == "net"]
    assert [(e["text"], e.get("method")) for e in net] == [("صفحة الدرس", "POST"), ("قائمة الدروس", None)]


def test_page_labels():
    from neo.services.live import page_label
    assert page_label("/teacher_lesson/show/1?lesson_id=2&section_id=3") == "قسم في الدرس"
    assert page_label("https://qeducation.edu.gov.qa/teacher_lesson/show/1?lesson_id=2") == "صفحة الدرس"
    assert page_label("/files/455212/x.docx?lmsauth=ab") == "ملف" and page_label("/x/y?z=1") == "/x/y"
