from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from neo.domain.types import ParsedAssessment, ParsedLesson
from neo.infrastructure.parsers import parse_assessments
from neo.models import AssignProposal, PlatformAssessment
from neo.services import safety
from neo.services.assign_service import (
    AssignPolicy,
    AssignService,
    plan_window,
    weekly_pick,
)
from neo.services.sync_service import SyncService
from neo.tests.helpers import confirm_matches

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def every_lesson(settings, request):
    """اختبارات المواعيد الأصلية تفترض إسناد كل درس؛ قاعدة الثلاثاء والخميس تُختبر صراحةً."""
    if "weekly" not in request.node.name:
        settings.NEO_ASSIGN_POLICY = {"due_days": 2, "allow_late": True}


def test_parse_assessments():
    items = parse_assessments((FIX / "assignments.html").read_text(encoding="utf-8"))
    assert items == [
        ParsedAssessment(15270548, "التقييم الختامي - حل المعادلات النسبية ( 3 )", 17844980, False),
        ParsedAssessment(14524052, "تقييم ختامي: قاعدتا الضرب والقسمة في الاشتقاق 2", 17065555, True),
    ]


def test_plan_window_future_and_past():
    p = AssignPolicy()
    b, e, f = plan_window(date(2026, 11, 10), TODAY, p)
    assert (b.date(), b.time(), e.date(), e.time(), f) == (date(2026, 11, 10), time(7), date(2026, 11, 12),
                                                             time(23, 59), [])
    b, e, f = plan_window(date(2026, 10, 5), TODAY, p)
    assert (b.date(), e.date()) == (TODAY, date(2026, 11, 4)) and f


@pytest.fixture
def setup(classes):
    k = classes[602598]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "حل المعادلات النسبية(1)", "", date(2026, 10, 5), 3),
        ParsedLesson(2, 2, "حل المعادلات النسبية(2)", "", date(2026, 11, 10), 6),
        ParsedLesson(3, 3, "حل المعادلات النسبية(3)", "", None, None),
    ], [])
    confirm_matches(k)
    svc = AssignService()
    svc.ingest(k, [
        ParsedAssessment(101, "تقييم 1", 1, False),
        ParsedAssessment(102, "تقييم 2", 2, False),
        ParsedAssessment(103, "تقييم 3", 3, False),
        ParsedAssessment(104, "تقييم مسند", 2, True),
    ])
    return svc, k


def test_plan(setup):
    svc, k = setup
    run = svc.plan(k, TODAY)
    props = {p.assessment.lms_assignment_id: p for p in run.assign_proposals.select_related("assessment")}
    assert set(props) == {101, 102}
    assert timezone.localtime(props[101].begin_at).date() == TODAY and props[101].flags
    assert timezone.localtime(props[102].end_at) == datetime(2026, 11, 12, 23, 59, tzinfo=timezone.get_default_timezone())
    assert run.summary["already_given"] == ["تقييم مسند"] and run.summary["no_lesson_date"] == ["تقييم 3"]


class FakeClient:
    def __init__(self, given=(), fail_window=(), saved=None, skew=None):
        self.given, self.fail_window, self.windows, self.gives = set(given), set(fail_window), [], []
        self.saved = dict(saved or {})  # aid → (البداية، الاستحقاق) كما على المنصة
        self.skew = skew                # المنصة تحفظ غير المرسل (كتابة خاطئة)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def assessments_html(self, lms_id):
        rows = "".join(
            f'<tr><td><input name="select[]" value="{i}"></td><td class="assignment"><a href="#">t</a></td>'
            f'<td>{"<i class=tick></i>" if i in self.given else ""}</td></tr>' for i in (101, 102, 103, 104))
        return f"<table>{rows}</table>"

    def assessment_window(self, aid):
        return self.saved.get(aid, ("", ""))

    def set_assessment_window(self, aid, begin, end, allow_late):
        if aid in self.fail_window:
            raise RuntimeError("boom")
        self.windows.append((aid, begin, end, allow_late))
        if self.skew:
            begin, end = begin + self.skew, end + self.skew
        self.saved[aid] = (f"{begin:%Y-%m-%d %H:%M}", f"{end:%Y-%m-%d %H:%M}")

    def give_assessments(self, lms_id, ids):
        self.gives.append(list(ids))
        self.given |= set(ids)


def test_apply_sets_window_then_gives_and_is_idempotent(setup):
    svc, k = setup
    run = svc.plan(k, TODAY)
    svc.approve(run.pk)
    client = FakeClient()
    log = svc.apply(run, lambda: client, TODAY)
    # 101 درسه ماضٍ: مواعيد + إسناد يدوي. 102 مستقبلي: مواعيد فقط، وتُسنده المنصة حين يصير درسه الحالي
    assert [w[0] for w in client.windows] == [101, 102] and client.gives == [[101]]
    assert client.windows[0][1] == datetime(2026, 11, 2, 7, 0) and client.windows[0][3] is True
    st = dict(run.assign_proposals.values_list("assessment__lms_assignment_id", "status"))
    assert st == {101: "applied", 102: "applied"} and log.ok
    assert PlatformAssessment.objects.get(lms_assignment_id=101).given
    assert not PlatformAssessment.objects.get(lms_assignment_id=102).given
    assert "تلقائيًا" in run.assign_proposals.get(assessment__lms_assignment_id=102).error
    # إعادة التطبيق: المُسند يُتخطّى، والمضبوط كما اعتُمد لا تُعاد كتابته
    AssignProposal.objects.filter(run=run).update(status="approved")
    client2 = FakeClient(given={101}, saved=client.saved)
    svc.apply(run, lambda: client2, TODAY)
    assert client2.windows == [] and client2.gives == []
    assert run.assign_proposals.get(assessment__lms_assignment_id=101).status == "skipped"


def test_apply_stops_at_first_error(setup):
    """الخطوة 5: أول خطأ غير متوقع يوقف التطبيق كله ولا إسناد بعده؛ ما لم يُجرَّب يبقى معتمدًا."""
    svc, k = setup
    run = svc.plan(k, TODAY)
    svc.approve(run.pk)
    client = FakeClient(fail_window={101})
    log = svc.apply(run, lambda: client, TODAY)
    assert client.windows == [] and client.gives == []
    st = dict(run.assign_proposals.values_list("assessment__lms_assignment_id", "status"))
    assert st == {101: "failed", 102: "approved"}
    assert not log.ok and log.summary["not_attempted"] == 1 and not safety.state().halted


def test_apply_wrong_write_halts(setup):
    """يوم غير المعتمد على المنصة بعد الحفظ = كتابة خاطئة: يتوقف ويوقف الكتابة كلها."""
    svc, k = setup
    run = svc.plan(k, TODAY)
    svc.approve(run.pk)
    log = svc.apply(run, lambda: FakeClient(skew=timedelta(days=1)), TODAY)
    p101 = run.assign_proposals.get(assessment__lms_assignment_id=101)
    assert p101.status == "failed" and "غير مطابقة" in p101.error and not log.ok
    assert safety.state().halted


def test_apply_keeps_existing_windows(setup, settings):
    """إضافة فقط (قرار المعلم): مواعيد قائمة على المنصة تخالف المعتمد لا تُمس، وتُنبَّه في الملخص."""
    svc, k = setup
    run = svc.plan(k, TODAY)
    svc.approve(run.pk)
    client = FakeClient(saved={102: ("2026-11-10 08:00", "2026-11-13 23:59")})  # ضُبطت يدويًا
    log = svc.apply(run, lambda: client, TODAY)
    assert [w[0] for w in client.windows] == [101] and log.ok
    p102 = run.assign_proposals.get(assessment__lms_assignment_id=102)
    assert p102.status == "skipped" and "يدويًا" in p102.error
    assert log.summary["kept_on_platform"] == ["تقييم 2: 2026-11-10 08:00 ← 2026-11-13 23:59"]
    # ما كتبته الأتمتة ثم تغيّر المعتمد (مهلة أطول): لا يُمس أيضًا، ويُذكر أنه منها
    settings.NEO_ASSIGN_POLICY = {"due_days": 3}
    first = svc.plan(k, TODAY)
    svc.approve(first.pk)
    svc.apply(first, lambda: FakeClient(), TODAY)  # 101 و102 بالمهلة الجديدة
    done = FakeClient(saved={102: ("2026-11-10 07:00", "2026-11-13 23:59")})
    settings.NEO_ASSIGN_POLICY = {"due_days": 2}
    again = svc.plan(k, TODAY)
    svc.approve(again.pk)
    svc.apply(again, lambda: done, TODAY)
    p = again.assign_proposals.get(assessment__lms_assignment_id=102)
    assert p.status == "skipped" and "الأتمتة" in p.error and 102 not in [w[0] for w in done.windows]


def test_weekly_pick_tuesday_and_thursday_one_each(classes):
    k = classes[602598]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "أ", "", date(2026, 11, 15), 3),   # الأحد
        ParsedLesson(2, 2, "ب", "", date(2026, 11, 17), 1),   # الثلاثاء
        ParsedLesson(3, 3, "ج", "", date(2026, 11, 17), 6),   # الثلاثاء (الأخير يُختار)
        ParsedLesson(4, 4, "د", "", date(2026, 11, 18), 2),   # الأربعاء
        ParsedLesson(5, 5, "هـ", "", date(2026, 11, 19), 1),  # الخميس
        ParsedLesson(6, 6, "و", "", date(2026, 11, 24), 1),   # ثلاثاء الأسبوع التالي
        ParsedLesson(7, 7, "ز", "", None, None),
    ], [])
    from neo.models import PlatformLesson
    lessons = list(PlatformLesson.objects.filter(klass=k))
    assert weekly_pick(lessons, (1, 3)) == {3, 5, 6}
    assert weekly_pick(lessons, ()) == {1, 2, 3, 4, 5, 6, 7}


def test_weekly_plan_only_proposes_picked_days(classes, settings):
    settings.NEO_ASSIGN_POLICY = {"due_days": 2, "allow_late": True, "weekdays": (1, 3)}
    k = classes[602598]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "أ", "", date(2026, 11, 16), 3),   # الاثنين
        ParsedLesson(2, 2, "ب", "", date(2026, 11, 17), 1),   # الثلاثاء
        ParsedLesson(3, 3, "ج", "", date(2026, 11, 19), 1),   # الخميس
    ], [])
    confirm_matches(k)
    svc = AssignService()
    svc.ingest(k, [ParsedAssessment(101, "ت1", 1, False), ParsedAssessment(102, "ت2", 2, False),
                   ParsedAssessment(103, "ت3", 3, False)])
    run = svc.plan(k, date(2026, 11, 12))
    got = {p.assessment.lms_assignment_id: timezone.localtime(p.begin_at).date() for p in run.assign_proposals.all()}
    assert got == {102: date(2026, 11, 17), 103: date(2026, 11, 19)}
    assert run.summary["not_weekly"] == 1 and run.summary["policy"]["weekdays"] == [1, 3]


# ------------------------------------------------------------- إسناد اليوم (واجب الثلاثاء وتقييم الخميس)

class GiveFake:
    def __init__(self, refuse=False):
        self.given, self.refuse, self.calls = set(), refuse, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def assessments_html(self, lms):
        return "x"

    def give_assessments(self, lms, ids):
        self.calls.append(list(ids))
        if not self.refuse:
            self.given |= set(ids)


@pytest.fixture
def weekly_setup(classes, settings, monkeypatch):
    settings.NEO_ASSIGN_POLICY = {"due_days": 2, "allow_late": True, "weekdays": (1, 3)}
    k = classes[602598]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "أ", "", date(2026, 11, 16), 3),   # الاثنين
        ParsedLesson(2, 2, "ب", "", date(2026, 11, 17), 1),   # الثلاثاء
        ParsedLesson(3, 3, "ج", "", date(2026, 11, 19), 1),   # الخميس
    ], [])
    confirm_matches(k)
    svc = AssignService()
    items = [ParsedAssessment(101, "ت1", 1, False), ParsedAssessment(102, "ت2", 2, False),
             ParsedAssessment(103, "ت3", 3, False)]
    svc.ingest(k, items)
    fake = GiveFake()
    from neo.services import assign_service
    monkeypatch.setattr(assign_service, "parse_assessments", lambda html: [
        ParsedAssessment(a.lms_assignment_id, a.title, a.lms_lesson_id, a.lms_assignment_id in fake.given)
        for a in items])
    # مواعيد مضبوطة بانتظار يومها، ومنها اقتراح قديم لدرس الاثنين كتبته دورة سابقة قبل القاعدة
    run = svc.plan(k, date(2026, 11, 12))
    run.assign_proposals.update(status=AssignProposal.Status.APPLIED, error=assign_service.GIVE_NOTE)
    old = PlatformAssessment.objects.get(lms_assignment_id=101)
    AssignProposal.objects.create(run=run, assessment=old, lesson_date=date(2026, 11, 16),
                                  begin_at=timezone.now(), end_at=timezone.now(), allow_late=True,
                                  status=AssignProposal.Status.APPLIED, error=assign_service.AUTO_GIVE_NOTE)
    return svc, k, fake


def test_weekly_give_due_only_on_its_day(weekly_setup):
    svc, k, fake = weekly_setup
    assert svc.give_due(k, date(2026, 11, 16), lambda: fake) is None and not fake.calls  # الاثنين: القديم خارج القاعدة
    run = svc.give_due(k, date(2026, 11, 17), lambda: fake)
    assert run.ok and fake.calls == [[102]] and run.summary["given"] == ["ت2"]
    assert PlatformAssessment.objects.get(lms_assignment_id=102).given
    assert svc.give_due(k, date(2026, 11, 17), lambda: fake) is None  # لا يتكرر
    run = svc.give_due(k, date(2026, 11, 19), lambda: fake)
    assert run.ok and fake.calls[-1] == [103]


def test_weekly_give_due_refused_is_retried_then_expires(weekly_setup):
    svc, k, fake = weekly_setup
    fake.refuse = True
    run = svc.give_due(k, date(2026, 11, 17), lambda: fake)
    assert not run.ok and run.summary["failed"] == ["ت2"] and "يُعاد" in run.summary["stopped"]
    fake.refuse = False
    assert svc.give_due(k, date(2026, 11, 18), lambda: fake).ok  # استدراك داخل المهلة
    assert not svc.due_to_give(k, date(2026, 11, 25))  # تقييم الخميس بعد فوات مهلته لا يُستدرك


def test_weekly_give_job_and_schedule(weekly_setup):
    from neo.models import Job
    from neo.services import weekly_service
    from neo.services.job_service import JobService

    assert weekly_setup
    tz = timezone.get_default_timezone()
    assert not weekly_service.give_due_now(datetime(2026, 11, 16, 9, 0, tzinfo=tz))
    assert not weekly_service.give_due_now(datetime(2026, 11, 17, 6, 0, tzinfo=tz))
    assert weekly_service.give_due_now(datetime(2026, 11, 17, 7, 5, tzinfo=tz))
    job, created = JobService().enqueue("assign_give")
    assert created and job.kind == Job.Kind.ASSIGN_GIVE
    assert not weekly_service.give_due_now(datetime(2026, 11, 17, 7, 6, tzinfo=tz))  # مهمة قائمة
    s = safety.state()
    s.halted, s.reason = True, "اختبار"
    s.save()
    job.delete()
    assert not weekly_service.give_due_now(datetime(2026, 11, 17, 7, 5, tzinfo=tz))
