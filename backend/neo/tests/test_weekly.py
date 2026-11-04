"""الدورة الأسبوعية: موعدها واستدراكها، والصمّامات، والتقرير؛ بلا منصة."""
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from neo.domain.types import ParsedLesson
from neo.infrastructure.client import PlatformError
from neo.models import Job, PlatformLesson, PublishProposal, ScorecardSnapshot, SyncRun, TimetableSlot
from neo.services import weekly_service as w
from neo.services.job_service import JobService
from neo.services.publish_service import PublishService
from neo.services.sync_service import SyncService
from neo.tests.helpers import confirm_matches

QA = ZoneInfo("Asia/Qatar")
FIX = Path(__file__).parent / "fixtures"
LMS = 602598


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=QA)  # 9 نوفمبر 2026 اثنين


def test_cycle_start():
    assert w.cycle_start(at(9, 7)) == at(9, 7)
    assert w.cycle_start(at(9, 6)) == at(9, 7) - timedelta(days=7)
    assert w.cycle_start(at(12, 10)) == at(9, 7)
    assert w.next_run(at(9, 8)) == at(16, 7)


def test_due_cycle(db):
    assert w.due_cycle(at(9, 6)) is None              # قبل أول دورة بالجدول الجديد (since 9 نوفمبر)
    assert w.due_cycle(at(9, 7)) == "2026-11-09"
    assert w.due_cycle(at(15, 23)) == "2026-11-09"    # الجهاز كان مطفأً: تُستدرك مرة قبل الدورة التالية
    job, _ = JobService().enqueue(Job.Kind.WEEKLY, {"cycle": "2026-11-09"})
    assert w.due_cycle(at(9, 8)) is None               # نشطة
    Job.objects.filter(pk=job.pk).update(status=Job.Status.FAILED, finished_at=at(9, 8))
    assert w.due_cycle(at(9, 8, 30)) is None           # فشلت للتو: تُعاد بعد ساعة
    assert w.due_cycle(at(9, 10)) == "2026-11-09"
    Job.objects.filter(pk=job.pk).update(status=Job.Status.DONE)
    assert w.due_cycle(at(9, 10)) is None              # تمت: لا تتكرر


def test_due_cycle_resumes_right_after_login(db):
    """فشلت لانتهاء الجلسة: تُستأنف فور الدخول بلا انتظار الساعة (الخطوة 0)."""
    svc = JobService()
    job, _ = svc.enqueue(Job.Kind.WEEKLY, {"cycle": "2026-11-09"})
    Job.objects.filter(pk=job.pk).update(status=Job.Status.FAILED, error_kind=Job.Error.SESSION, finished_at=at(9, 7, 5))
    assert w.due_cycle(at(9, 7, 6)) is None
    check, _ = svc.enqueue(Job.Kind.SESSION)
    Job.objects.filter(pk=check.pk).update(status=Job.Status.DONE, finished_at=at(9, 7, 8))
    assert w.due_cycle(at(9, 7, 10)) == "2026-11-09"


def test_enqueue_due_is_idempotent_and_warns_when_late(db, monkeypatch):
    svc, late = JobService(), []
    monkeypatch.setattr(w.alerts, "late_cycle", lambda start: late.append(start))
    a = w.enqueue_due(at(9, 7), svc.enqueue)
    assert a.kind == Job.Kind.WEEKLY and w.enqueue_due(at(9, 7), svc.enqueue) is None and late == []
    Job.objects.filter(pk=a.pk).update(status=Job.Status.FAILED, finished_at=at(9, 7))
    w.enqueue_due(at(10, 9), svc.enqueue)  # الجهاز شُغّل صباح الثلاثاء: استدراك مع تنبيه بالتأخير
    assert late == [at(9, 7)]


def test_periods_in_window(classes):
    """الحد = عدد حصص الصف في النافذة، من جدوله وأسابيع التدريس في خطته."""
    k = classes[LMS]
    TimetableSlot.objects.create(klass=k, weekday=0, period=1)  # الاثنين
    TimetableSlot.objects.create(klass=k, weekday=2, period=3)  # الأربعاء
    week = k.plan.weeks.filter(week_type="تدريس").order_by("week_no").first()
    sunday = week.start_date
    assert w.periods_in_window(k, sunday + timedelta(days=1), sunday + timedelta(days=1)) == 1
    assert w.periods_in_window(k, sunday, sunday + timedelta(days=6)) == 2
    assert w.periods_in_window(k, sunday + timedelta(days=4), sunday + timedelta(days=4)) == 0  # الخميس


def test_disabled(db, settings):
    settings.NEO_WEEKLY = {"enabled": False}
    assert w.due_cycle(at(5, 14)) is None


@pytest.fixture
def publish_run(classes):
    k = classes[LMS]
    SyncService().ingest(k, [ParsedLesson(i, i, f"درس {i}", "", date(2026, 11, 6), 1, hidden=True)
                             for i in range(1, 4)], [])
    confirm_matches(k)
    return PublishService().plan(k)


def test_auto_approve(publish_run, settings):
    settings.NEO_WEEKLY = {"auto_approve": True}
    qs = publish_run.publish_proposals.all()
    stage = {}
    assert w._auto_approve(qs, qs.filter(lesson__position__lte=2), stage, 10) == 2
    assert stage == {"proposals": 3, "eligible": 2, "held": 1, "approved": 2, "limit": 10}


def test_auto_approve_anomaly(publish_run, settings):
    settings.NEO_WEEKLY = {"auto_approve": True}
    qs = publish_run.publish_proposals.all()
    stage = {}
    assert w._auto_approve(qs, qs, stage, 2) == 0 and "حصص" in stage["anomaly"] and stage["held"] == 3
    assert not qs.filter(status=PublishProposal.Status.APPROVED).exists()


def test_auto_approve_review_only(publish_run, settings):
    """للمراجعة فقط (قرار المعلم 2026-11-04): لا يُعتمد شيء آليًا ولو كان مؤهَّلًا، وكل المعلّق يبقى للمراجعة."""
    settings.NEO_WEEKLY = {"auto_approve": False}
    qs = publish_run.publish_proposals.all()
    stage = {}
    assert w._auto_approve(qs, qs, stage, 10) == 0
    assert stage["held"] == 3 and stage["approved"] == 0 and stage["review_only"] is True and "anomaly" not in stage
    assert not qs.filter(status=PublishProposal.Status.APPROVED).exists()


def test_fetch_refuses_shrunk_page(classes):
    """صفحة بدروس أقل كثيرًا من المحفوظ: لا يُحذف شيء محليًا."""
    k = classes[LMS]
    SyncService().ingest(k, [ParsedLesson(10_000 + i, i, f"درس {i}", "", None, None) for i in range(200)], [])

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def lesson_list_html(self, lms_id):
            return (FIX / "lesson_list.html").read_text(encoding="utf-8")

        def timetable_html(self, lms_id):
            return ""

    with pytest.raises(PlatformError, match="نقص"):
        SyncService().fetch([k], Client)
    assert PlatformLesson.objects.filter(klass=k).count() == 200


def _fake_pipeline(monkeypatch, k, publish_run, calls):
    def run(kind, **summary):
        return SyncRun.objects.create(klass=k, kind=kind, ok=True, summary=summary, finished_at=timezone.now())

    monkeypatch.setattr(w.pipeline, "sync_plan", lambda c, f, t: calls.append("dates") or [run(SyncRun.Kind.PLAN)])
    monkeypatch.setattr(w.pipeline, "assign_plan",
                        lambda c, f, t: calls.append("assign") or [run(SyncRun.Kind.ASSIGN_PLAN)])
    monkeypatch.setattr(w.pipeline, "publish_plan", lambda c, f: calls.append("publish") or [publish_run])
    monkeypatch.setattr(w.pipeline, "publish_apply", lambda r, f, t: calls.append("apply") or [
        run(SyncRun.Kind.PUBLISH_APPLY, applied=3), run(SyncRun.Kind.VERIFY, missing_past=[])])
    monkeypatch.setattr(w.pipeline, "verify", lambda c, f, t: calls.append("verify") or [])
    monkeypatch.setattr(w.pipeline, "prep_pack", lambda lms, week, f: calls.append("prep") or [
        run(SyncRun.Kind.PREP, folder=f"W{week:03d}")])
    monkeypatch.setattr(w, "periods_in_window", lambda klass, start, end: 10)


def test_run_review_only(publish_run, monkeypatch, settings):
    """للمراجعة فقط: الدورة تجلب وتقترح وتتحقق، ولا تطبيق (لا كتابة على المنصة)، والتقرير ينبّه لما ينتظر المعلم."""
    settings.NEO_WEEKLY = {"auto_approve": False}
    k, calls = publish_run.klass, []
    _fake_pipeline(monkeypatch, k, publish_run, calls)
    report = {}
    w.run([k], None, date(2026, 11, 5), report)
    assert calls == ["dates", "assign", "publish", "verify", "prep"]  # لا apply
    publish = report["classes"][k.name]["publish"]
    assert publish["held"] == 3 and publish["review_only"] is True and report["attention"] >= 1
    assert not publish_run.publish_proposals.filter(status=PublishProposal.Status.APPROVED).exists()


def test_run_report(publish_run, monkeypatch, settings):
    """المراحل بالترتيب، والمعتمد آليًا يُطبَّق، والتقرير يبقى في المهمة."""
    settings.NEO_WEEKLY = {"auto_approve": True}
    k, calls = publish_run.klass, []
    _fake_pipeline(monkeypatch, k, publish_run, calls)
    report = {}
    w.run([k], None, date(2026, 11, 5), report)
    assert calls == ["dates", "assign", "publish", "apply", "prep"]  # النشر تحقق، فلا تحقق ثانٍ؛ ثم الحزمة
    stages = report["classes"][k.name]
    assert stages["publish"]["applied"] == 3 and stages["verify"]["ok"] is True
    week = w.next_teaching_week(k, date(2026, 11, 5))
    assert stages["prep"] == {"week": week, "ok": True, "folder": f"W{week:03d}"}
    assert stages["dates"]["approved"] == 0 and report["attention"] == 0
    assert ScorecardSnapshot.objects.filter(day=date(2026, 11, 5)).exists()  # لقطة بعد كل دورة


def test_run_prep_failure_is_reported_not_fatal(publish_run, monkeypatch, settings):
    """تعذّر حزمة صف يُسجَّل في التقرير ويحتاج نظر المعلم، ولا يوقف الدورة ولا لقطة بطاقة الأداء."""
    settings.NEO_WEEKLY = {"auto_approve": False}
    k, calls = publish_run.klass, []
    _fake_pipeline(monkeypatch, k, publish_run, calls)

    def stopped(lms, week, f):
        raise w.pipeline.PipelineError("عدد دروس الأسبوع لا يساوي عدد الحصص")

    monkeypatch.setattr(w.pipeline, "prep_pack", stopped)
    report = {}
    w.run([k], None, date(2026, 11, 5), report)
    prep = report["classes"][k.name]["prep"]
    assert prep["ok"] is False and "الحصص" in prep["error"] and report["attention"] >= 1
    assert ScorecardSnapshot.objects.filter(day=date(2026, 11, 5)).exists()
