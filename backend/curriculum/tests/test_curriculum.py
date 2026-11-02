from datetime import date

import pytest
from django.conf import settings
from django.db.models import Sum

from curriculum import models as m
from curriculum.services.import_service import PlanImportService
from curriculum.services.schedule_service import ScheduleService

pytestmark = pytest.mark.django_db


@pytest.fixture
def imported():
    return PlanImportService(settings.PLANS_DIR).run()


def plan_id(grade: int) -> int:
    return m.Plan.objects.get(grade_level=grade).pk


def test_import_counts(imported):
    assert (imported.plans, imported.lessons, imported.entries, imported.outcomes) == (2, 38, 62, 17)


def test_import_is_idempotent(imported):
    again = PlanImportService(settings.PLANS_DIR).run()
    assert again == imported
    assert m.Competency.objects.count() == 5


@pytest.mark.parametrize("grade,total", [(10, 63), (12, 74)])
def test_total_periods_match_source(imported, grade, total):
    assert m.ScheduleEntry.objects.filter(plan__grade_level=grade).aggregate(s=Sum("periods"))["s"] == total


def test_current_week_and_weekend_rollover(imported):
    svc = ScheduleService()
    wk = svc.week_for_date(plan_id(12), date(2026, 11, 2))
    assert (wk.week_no, wk.status, wk.total_periods) == (10, "current", 6)
    assert [e.lesson_code for e in wk.entries] == ["2.9", None, "3.1"]
    friday = svc.week_for_date(plan_id(10), date(2026, 11, 6))
    assert (friday.week_no, friday.status) == (11, "upcoming")
    assert svc.week_for_date(plan_id(10), date(2026, 12, 20)) is None


def test_break_week_has_event(imported):
    wk = ScheduleService().week_by_no(plan_id(10), 9)
    assert wk.week_type == "إجازة" and wk.total_periods == 0
    assert any(e.event_type == "إجازة" for e in wk.events)


def test_progress(imported):
    p = ScheduleService().progress(plan_id(10), date(2026, 11, 1))
    assert p.planned_periods_done == 38 and p.total_periods == 63
    assert "2.6 القانون العام لحل المعادلة التربيعية والمميز" in p.lessons_done
    assert p.lessons_remaining[0].startswith("2.7")


def test_api_current_week(imported, client):
    r = client.get(f"/api/plans/{plan_id(12)}/current-week/?date=2026-11-02", REMOTE_ADDR="127.0.0.1")
    assert r.status_code == 200 and r.json()["week_no"] == 10


def test_api_plan_filters_and_calendar_dedup(imported, client):
    r = client.get("/api/plans/?year=2026-2027&term=1&grade=12", REMOTE_ADDR="127.0.0.1").json()
    assert [p["grade_level"] for p in r] == [12]
    events = client.get("/api/calendar/?year=2026-2027&term=1", REMOTE_ADDR="127.0.0.1").json()
    keys = [(e["title"], e["start_date"]) for e in events]
    assert keys and len(keys) == len(set(keys))


def test_import_is_additive_and_keeps_plan_ids(imported):
    """خطة فصل آخر لا يمسها الاستيراد، وإعادة الاستيراد لا تغيّر معرّف الخطة."""
    g10 = m.Plan.objects.get(grade_level=10)
    other = m.Plan.objects.create(
        document=m.SourceDocument.objects.create(form_code="X", issue_no=1, issue_date=date(2027, 1, 1),
                                                 classification="عام", department="قسم", file_name="t2.pdf",
                                                 page_count=1),
        subject=g10.subject, academic_year="2026-2027", term_no=2, grade_level=10, shift=g10.shift)
    again = PlanImportService(settings.PLANS_DIR).run()
    assert again == imported
    assert m.Plan.objects.filter(pk=other.pk).exists() and m.Plan.objects.get(grade_level=10, term_no=1).pk == g10.pk


def test_admin_auto_login_on_loopback(client):
    r = client.get("/admin/", REMOTE_ADDR="127.0.0.1")
    assert r.status_code == 200
    user = m.Plan._meta.apps.get_model("auth", "User").objects.get(username="admin")
    assert user.is_superuser and not user.has_usable_password()


def test_non_loopback_rejected(client):
    assert client.get("/admin/", REMOTE_ADDR="192.168.1.20").status_code == 403
