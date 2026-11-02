from datetime import date, datetime, time
from pathlib import Path

import pytest
from django.utils import timezone

from neo.domain.types import ParsedAssessment, ParsedLesson
from neo.infrastructure.parsers import parse_assessments
from neo.models import AssignProposal, PlatformAssessment
from neo.services.assign_service import AssignPolicy, AssignService, plan_window
from neo.services.sync_service import SyncService

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 2)


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
def setup(db, settings):
    from curriculum.services.import_service import PlanImportService
    PlanImportService(settings.PLANS_SOURCE_DB).run()
    k = {c.lms_id: c for c in SyncService().ensure_classes()}[602598]
    SyncService().ingest(k, [
        ParsedLesson(1, 1, "حل المعادلات النسبية(1)", "", date(2026, 10, 5), 3),
        ParsedLesson(2, 2, "حل المعادلات النسبية(2)", "", date(2026, 11, 10), 6),
        ParsedLesson(3, 3, "حل المعادلات النسبية(3)", "", None, None),
    ], [])
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
    def __init__(self, given=(), fail_window=()):
        self.given, self.fail_window, self.windows, self.gives = set(given), set(fail_window), [], []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def assessments_html(self, lms_id):
        rows = "".join(
            f'<tr><td><input name="select[]" value="{i}"></td><td class="assignment"><a href="#">t</a></td>'
            f'<td>{"<i class=tick></i>" if i in self.given else ""}</td></tr>' for i in (101, 102, 103, 104))
        return f"<table>{rows}</table>"

    def set_assessment_window(self, aid, begin, end, allow_late):
        if aid in self.fail_window:
            raise RuntimeError("boom")
        self.windows.append((aid, begin, end, allow_late))

    def give_assessments(self, lms_id, ids):
        self.gives.append(list(ids))
        self.given |= set(ids)


def test_apply_sets_window_then_gives_and_is_idempotent(setup):
    svc, k = setup
    run = svc.plan(k, TODAY)
    svc.approve(run.pk)
    client = FakeClient(fail_window={102})
    log = svc.apply(run, lambda: client, TODAY)
    # 101 درسه ماضٍ: مواعيد + إسناد يدوي. 102 فشل ضبط مواعيده فلا يُسند
    assert [w[0] for w in client.windows] == [101] and client.gives == [[101]]
    assert client.windows[0][1] == datetime(2026, 11, 2, 7, 0) and client.windows[0][3] is True
    st = dict(run.assign_proposals.values_list("assessment__lms_assignment_id", "status"))
    assert st == {101: "applied", 102: "failed"}
    assert PlatformAssessment.objects.get(lms_assignment_id=101).given
    assert log.summary == {"plan_run": run.pk, "applied": 1, "failed": 1}
    # إعادة التطبيق: المُسند يُتخطّى، والمستقبلي يُضبط ولا يُسند يدويًا (تتولاه المنصة)
    AssignProposal.objects.filter(run=run).update(status="approved")
    client2 = FakeClient(given={101})
    svc.apply(run, lambda: client2, TODAY)
    assert [w[0] for w in client2.windows] == [102] and client2.gives == []
    p102 = run.assign_proposals.get(assessment__lms_assignment_id=102)
    assert p102.status == "applied" and "تلقائيًا" in p102.error
    assert not PlatformAssessment.objects.get(lms_assignment_id=102).given
    assert run.assign_proposals.get(assessment__lms_assignment_id=101).status == "skipped"
