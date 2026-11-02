from dataclasses import replace
from datetime import date

import pytest
from django.conf import settings
from openpyxl import load_workbook

from curriculum import models as m
from curriculum.domain.plan_spec import PlanFileError
from curriculum.infrastructure.plan_workbook import plan_files, read_plan, write_plan
from curriculum.services.import_service import PlanImportService
from curriculum.services.plan_export import spec_from_plan

G10 = settings.PLANS_DIR / "2026-2027" / "ف1" / "الرياضيات_10.xlsx"


@pytest.fixture(scope="module")
def spec():
    return read_plan(G10)


def test_repo_plan_files_are_valid():
    files = plan_files(settings.PLANS_DIR)
    assert len(files) == 2
    totals = {s.grade_level: sum(s.week_totals().values()) for s in map(read_plan, files)}
    assert totals == {10: 63, 12: 74}


def test_spec_derivations(spec):
    lessons = {c: (in_s, p) for _, c, _, in_s, p in spec.lessons()}
    assert lessons["2.3"] == (True, 4) and lessons["1.4"] == (False, 0)
    assert spec.week_totals()[9] == 0


def test_write_read_roundtrip(spec, tmp_path):
    assert read_plan(write_plan(spec, tmp_path / "x.xlsx")) == spec


@pytest.mark.django_db
def test_db_export_roundtrip(spec):
    PlanImportService(G10).run()
    assert spec_from_plan(m.Plan.objects.get()) == spec


@pytest.mark.parametrize("change,message", [
    (lambda s: replace(s, weeks=(replace(s.weeks[0], start_date=date(2026, 8, 31)),) + s.weeks[1:]), "الأحد"),
    (lambda s: replace(s, weeks=(replace(s.weeks[0], expected_periods=9),) + s.weeks[1:]), "مجموع الأسبوع 1"),
    (lambda s: replace(s, entries=s.entries + (replace(s.entries[0], week_no=9),)), "إجازة"),
    (lambda s: replace(s, entries=s.entries + (replace(s.entries[1], unit_no=3),)), "وحدتين"),
    (lambda s: replace(s, enrichment=s.enrichment + (replace(s.enrichment[0], lesson_code="9.9"),)), "9.9"),
    (lambda s: replace(s, term_no=4), "الفصل"),
])
def test_validation_catches(spec, change, message):
    assert any(message in e for e in change(spec).validate())


def test_numeric_lesson_code_rejected(spec, tmp_path):
    path = write_plan(spec, tmp_path / "x.xlsx")
    wb = load_workbook(path)
    wb["التوزيع"]["D3"].value = 1.1  # الرمز رقمًا لا نصًا
    wb.save(path)
    with pytest.raises(PlanFileError) as exc:
        read_plan(path)
    assert any("نصًا" in e for e in exc.value.errors)


def test_template_is_empty_and_reports_required(tmp_path):
    with pytest.raises(PlanFileError) as exc:
        read_plan(write_plan(None, tmp_path / "t.xlsx"))
    assert any("المادة" in e for e in exc.value.errors)


@pytest.mark.django_db
def test_bad_file_aborts_whole_import(spec, tmp_path):
    write_plan(spec, tmp_path / "a.xlsx")
    write_plan(replace(spec, grade_level=11, term_no=4), tmp_path / "b.xlsx")
    with pytest.raises(PlanFileError):
        PlanImportService(tmp_path).run()
    assert not m.Plan.objects.exists()
