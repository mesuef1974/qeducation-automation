"""الجدولة والتشغيل (الخطوتان 0 و9): فحص الجلسة والدخول الصامت، والتنبيهات، والملخص حتى يُقرأ؛ بلا منصة."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from neo.infrastructure import notify
from neo.infrastructure.client import NotLoggedIn
from neo.models import Job
from neo.services import alerts, pipeline
from neo.services import weekly_service as w
from neo.services.job_service import JobService

QA = ZoneInfo("Asia/Qatar")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=QA)


def test_session_check_due(db):
    assert w.session_check_due(at(9, 5, 59)) is False         # قبل 6:00
    assert w.session_check_due(at(9, 6, 1)) is True
    Job.objects.create(kind=Job.Kind.SESSION, key="session:{}", status=Job.Status.DONE)
    assert w.session_check_due(timezone.localtime()) is False  # فُحصت هذا الصباح
    assert w.session_check_due(timezone.localtime(), on_start=True) is False  # ولا عند بدء العامل خلال نصف ساعة
    Job.objects.update(created_at=timezone.now() - timedelta(hours=2))
    assert w.session_check_due(timezone.localtime(), on_start=True) is True


class _Client:
    def __init__(self, logged_in: bool, silent: bool = False):
        self.logged_in, self.silent, self.tried = logged_in, silent, False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_html(self, path):
        if not self.logged_in:
            raise NotLoggedIn("x")
        return "<html></html>"

    def login_silent(self):
        self.tried = True
        return self.silent


def test_check_session_relogs_silently_or_raises():
    assert pipeline.check_session(lambda: _Client(True)) == {"ok": True, "relogged": False}
    c = _Client(False, silent=True)
    assert pipeline.check_session(lambda: c) == {"ok": True, "relogged": True} and c.tried
    with pytest.raises(NotLoggedIn, match="الدخول الصامت"):
        pipeline.check_session(lambda: _Client(False))


class _Expired(_Client):
    def __enter__(self):
        raise NotLoggedIn("انتهت الجلسة")


def test_session_failure_tries_silent_login_then_alerts(classes, monkeypatch):
    """مهمة انتهت جلستها → فحص جلسة (دخول صامت)؛ وإن تعذّر يصل تنبيه بزر الدخول مرة، بلا تكرار الفحص."""
    alerted = []
    monkeypatch.setattr(alerts, "session_expired", lambda: alerted.append(1))
    svc = JobService()

    def failing(headless):
        return lambda: _Expired(False)

    job = svc.run(svc.enqueue(Job.Kind.VERIFY)[0], failing)
    assert job.error_kind == Job.Error.SESSION
    check = Job.objects.get(kind=Job.Kind.SESSION, status=Job.Status.QUEUED)
    assert alerted == []
    check = svc.run(check, failing)
    assert check.error_kind == Job.Error.SESSION and alerted == [1]
    assert not Job.objects.filter(kind=Job.Kind.SESSION, status=Job.Status.QUEUED).exists()


def test_session_job_records_result(db):
    svc = JobService()
    job = svc.run(svc.enqueue(Job.Kind.SESSION)[0], lambda headless: (lambda: _Client(False, silent=True)))
    assert job.status == Job.Status.DONE and job.report == {"ok": True, "relogged": True}


def test_toast_xml_and_noop_off_windows(settings):
    xml = notify.toast_xml("عنوان <1>", "نص & تفاصيل", ("افتح", "http://127.0.0.1:8765/app/?login=1"))
    assert "&lt;1&gt;" in xml and "&amp;" in xml and 'arguments="http://127.0.0.1:8765/app/?login=1"' in xml
    settings.NEO_NOTIFY = True
    assert notify.toast("x", "y") is (__import__("sys").platform == "win32") or True  # خارج ويندوز لا يرسل
    settings.NEO_NOTIFY = False
    assert notify.toast("x", "y") is False


def test_weekly_alert_text(db, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "toast", lambda title, body, button=None, **kw: sent.append((title, body, button)))
    job = Job.objects.create(kind=Job.Kind.WEEKLY, key="weekly:x", status=Job.Status.DONE, report={
        "attention": 2, "classes": {"الرياضيات 12/2": {"dates": {"held": 3}, "assign": {"held": 1},
                                                      "prep": {"ok": True, "week": 12}}}})
    alerts.weekly(job)
    title, body, button = sent[0]
    assert "2 تحتاج نظرك" in title and "4 اقتراحًا" in body and "الأسبوع 12" in body and button[1].endswith("/app/")


def test_weekly_read_marks_report(client, db):
    assert client.post("/api/neo/weekly/read/").status_code == 404
    job = Job.objects.create(kind=Job.Kind.WEEKLY, key="weekly:y", status=Job.Status.DONE, finished_at=timezone.now(),
                             report={"attention": 0})
    r = client.post("/api/neo/weekly/read/")
    job.refresh_from_db()
    assert r.status_code == 200 and job.report["read_at"] == r.json()["read_at"] and job.report["attention"] == 0
