import json
from datetime import date
from pathlib import Path

import pytest

from neo.domain.types import ParsedLesson, ParsedSlot
from neo.infrastructure.parsers import parse_date_label, parse_lessons, parse_timetable
from neo.models import DateProposal, PlatformLesson
from neo.services.matching import strip_part
from neo.services import safety
from neo.services.sync_service import SyncService, build_targets
from neo.tests.helpers import confirm_matches

FIX = Path(__file__).parent / "fixtures"
SNAP = json.loads((FIX / "lessons_snapshot.json").read_text(encoding="utf-8"))
YEAR = "2026-2027"


# ---------------------------------------------------------------- محللات

def test_parse_date_label():
    assert parse_date_label("أغسطس 30, الحصة 3", YEAR) == (date(2026, 8, 30), 3)
    assert parse_date_label("يناير 5", YEAR) == (date(2027, 1, 5), None)
    assert parse_date_label("", YEAR) == (None, None)


def test_parse_lessons_html():
    lessons = parse_lessons((FIX / "lesson_list.html").read_text(encoding="utf-8"), YEAR)
    assert [(p.lms_lesson_id, p.position) for p in lessons] == [(16646488, 1), (17053908, 25), (17844998, 47)]
    assert lessons[0].title == "تهيئة الفصل الدراسي الاول 1"
    assert (lessons[0].date, lessons[0].period, lessons[0].description) == (date(2026, 8, 30), 3, "")
    assert lessons[1].date is None and "القانون العام" in lessons[1].description


def test_parse_timetable_html():
    slots = parse_timetable((FIX / "lesson_list.html").read_text(encoding="utf-8"))
    assert slots == [ParsedSlot(0, 6), ParsedSlot(6, 3)]


@pytest.mark.parametrize("raw,clean", [
    ("إكمال المربع 3", "إكمال المربع"), ("الاتصال(2)", "الاتصال"),
    ("رسم منحنيات الدوال ج1", "رسم منحنيات الدوال"), ("إثبات تشابه المثلثات (ج1)", "إثبات تشابه المثلثات"),
])
def test_strip_part(raw, clean):
    assert strip_part(raw) == clean


# ---------------------------------------------------------------- مطابقة واقتراح (لقطة حقيقية)

@pytest.fixture
def loaded(classes):
    svc = SyncService()
    for lms_id, k in classes.items():
        lessons = []
        for i, (title, label) in enumerate(SNAP[str(lms_id)], 1):
            d, p = parse_date_label(label, YEAR) if label else (None, None)
            lessons.append(ParsedLesson(lms_id * 1000 + i, i, title, "", d, p))
        slots = [ParsedSlot(w, p) for w, p in SNAP["timetables"][str(lms_id)]]
        svc.ingest(k, lessons, slots)
        svc.match(k)
        confirm_matches(k)  # المعلم أكّد المطابقة مرة واحدة؛ اختبار الاستبعاد أدناه يلغيها لدرس
    return svc, classes


def codes(klass):
    return [pl.match_code for pl in PlatformLesson.objects.filter(klass=klass).order_by("position")]


def test_matching_grade10(loaded):
    svc, classes = loaded
    svc.plan(classes[602598], date(2026, 11, 1))
    c = codes(classes[602598])
    assert c[:2] == ["تهيئة#1"] * 2
    assert c[2:6] == ["1.1"] * 4 and c[6:10] == ["1.2"] * 4 and c[10:13] == ["1.3"] * 3
    assert c[13] == "مراجعة واختبار وحدة#1"
    assert c[14:17] == ["2.1"] * 3 and c[17:19] == ["2.3"] * 2 and c[19:23] == ["2.5"] * 4
    assert c[23:26] == ["2.6"] * 3 and c[26:30] == ["2.7"] * 4 and c[30:33] == ["2.8"] * 3
    assert c[33:35] == ["2.9"] * 2 and c[35:38] == ["2.10"] * 3
    assert c[38:41] == ["3.3"] * 3 and c[41:44] == ["3.4"] * 3 and c[44:47] == ["3.5"] * 3


def test_matching_grade12(loaded):
    svc, classes = loaded
    svc.plan(classes[602728], date(2026, 11, 1))
    c = codes(classes[602728])
    expected = (["تهيئة#1"] * 2 + ["1.1"] * 4 + ["1.2"] * 4 + ["1.3"] * 3 + ["1.4"] * 4 + ["مراجعة واختبار وحدة#1"]
                + ["2.1"] * 4 + ["2.2"] * 3 + ["2.3"] * 3 + ["2.4"] * 3 + ["2.5"] * 3 + ["2.6"] * 3 + ["2.7"] * 4
                + ["2.8"] * 3 + ["2.9"] * 3 + ["3.1"] * 4 + ["3.2"] * 4 + ["3.3"] * 4 + ["3.4"] * 4 + ["3.5"] * 4)
    assert c == expected


def test_proposals_grade10(loaded):
    svc, classes = loaded
    run = svc.plan(classes[602598], date(2026, 11, 1))
    props = {p.lesson.position: p for p in run.proposals.select_related("lesson")}
    assert len(props) == 23  # الدروس 25-47 غير المؤرخة
    # 2.6 (ج2، ج3) في الأسبوع 6 بعد آخر درس مؤرخ (1 أكتوبر)
    assert (props[25].proposed_date, props[25].proposed_period, props[25].plan_week_no) == (date(2026, 10, 4), 3, 6)
    assert props[26].proposed_date == date(2026, 10, 5)
    # 2.7 تبدأ الأسبوع 10 بعد الإجازة
    assert (props[27].proposed_date, props[27].proposed_period) == (date(2026, 11, 1), 3)
    assert all(p.plan_week_no != 9 for p in props.values())
    assert "تاريخ ماضٍ" in props[25].flags and props[27].flags == ""
    s = run.summary
    assert any(m.startswith("2.2 ") for m in s["missing_in_platform"])
    assert any(m.startswith("2.3 ") and "المنصة 2 / الخطة 4" in m for m in s["count_mismatch"])
    assert s["unmatched"] == []


def test_proposals_are_monotonic_and_unique(loaded):
    svc, classes = loaded
    for k in classes.values():
        run = svc.plan(k, date(2026, 11, 1))
        keys = [(p.proposed_date, p.proposed_period) for p in run.proposals.order_by("lesson__position")]
        assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_sandwiched_lesson_never_takes_occupied_slot(loaded):
    svc, classes = loaded
    run = svc.plan(classes[602728], date(2026, 11, 1))
    p27 = run.proposals.get(lesson__position=27)  # قواعد الاشتقاق 2 بين درسين مؤرخين متتاليين
    assert (p27.proposed_date, p27.proposed_period) == (date(2026, 9, 28), 2)
    assert "حصة مشتركة" in p27.flags
    dated = set(PlatformLesson.objects.filter(klass=classes[602728], date__isnull=False)
                .values_list("date", "period"))
    others = run.proposals.exclude(pk=p27.pk)
    assert not dated & {(p.proposed_date, p.proposed_period) for p in others}


def test_override_code_wins(loaded):
    svc, classes = loaded
    k = classes[602598]
    pl = PlatformLesson.objects.get(klass=k, position=47)
    pl.override_code = "-"
    pl.save()
    run = svc.plan(k, date(2026, 11, 1))
    assert "47. التناسب في المثلثات(ج3)" in run.summary["unmatched"]
    assert not run.proposals.filter(lesson=pl).exists()  # الخطوة 1: غير المطابق يُستبعد من الاقتراح
    assert any(x.startswith("47. ") for x in run.summary["unconfirmed_match"])


def test_unconfirmed_match_is_excluded_until_confirmed(loaded):
    """الخطوة 1: مطابقة دون 100% لم يؤكدها المعلم تُستبعد من الاقتراح وتُذكر؛ تأكيدها مرة واحدة يعيدها."""
    svc, classes = loaded
    k = classes[602598]
    pl = svc.plan(k, date(2026, 11, 1)).proposals.select_related("lesson").order_by("lesson__position").first().lesson
    # عنوان المنصة صار يختلف قليلًا عن الخطة: المطابقة الآلية دون 100% ولم يؤكدها المعلم بعد
    PlatformLesson.objects.filter(pk=pl.pk).update(title=f"{pl.title} تمارين إضافية", confirmed_code="")
    run = svc.plan(k, date(2026, 11, 1))
    pl.refresh_from_db()
    assert pl.match_code and pl.match_score < 0.999 and not pl.match_sure
    assert not run.proposals.filter(lesson=pl).exists()
    assert any(x.startswith(f"{pl.position}. ") for x in run.summary["unconfirmed_match"])
    PlatformLesson.objects.filter(pk=pl.pk).update(confirmed_code=pl.match_code)
    run = svc.plan(k, date(2026, 11, 1))
    assert run.proposals.filter(lesson=pl).exists() and run.summary["unconfirmed_match"] == []


def test_targets_cover_plan(loaded):
    _, classes = loaded
    t = {x.code: x for x in build_targets(classes[602598].plan)}
    assert t["2.3"].weeks == {4, 5} and t["2.3"].plan_periods == 4
    assert t["مشروع STEM#0"].weeks == {8}


# ---------------------------------------------------------------- تطبيق (عميل وهمي)

class FakeClient:
    def __init__(self, dated=(), saved=None):
        self.dated, self.writes, self.values = set(dated), [], {}
        self.saved = saved  # ما تعيده القراءة البعدية؛ None = ما كُتب فعلًا

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def lesson_has_date(self, lms_id, lesson_id):
        return lesson_id in self.dated

    def set_lesson_date(self, lms_id, lesson_id, d, period):
        self.writes.append((lesson_id, d, period))
        self.values[lesson_id] = (d.isoformat(), str(period))

    def lesson_date_value(self, lms_id, lesson_id):
        return self.saved if self.saved is not None else self.values.get(lesson_id, ("", ""))


def test_approve_future_only(loaded):
    svc, classes = loaded
    run = svc.plan(classes[602728], date(2026, 11, 1))
    assert svc.approve(run.pk, only_from=date(2026, 11, 1)) == 23
    assert run.proposals.filter(status="pending").count() == 9


def test_apply_only_approved_and_skips_dated(loaded):
    svc, classes = loaded
    k = classes[602598]
    run = svc.plan(k, date(2026, 11, 1))
    p25, p26, p27 = (run.proposals.get(lesson__position=n) for n in (25, 26, 27))
    DateProposal.objects.filter(pk__in=[p25.pk, p26.pk]).update(status=DateProposal.Status.APPROVED)
    client = FakeClient(dated={p26.lesson.lms_lesson_id})
    log = svc.apply(run, lambda: client)
    assert client.writes == [(p25.lesson.lms_lesson_id, date(2026, 10, 4), 3)]
    for p in (p25, p26, p27):
        p.refresh_from_db()
    assert (p25.status, p26.status, p27.status) == ("applied", "skipped", "pending")
    assert log.ok and log.summary["applied"] == 1
    # إعادة التطبيق لا تكتب شيئًا (Idempotent)
    client2 = FakeClient()
    svc.apply(run, lambda: client2)
    assert client2.writes == []


def test_apply_reads_back_and_stops(loaded):
    """الخطوة 5: قراءة بعدية لكل درس؛ لم يثبت → يتوقف بلا إيقاف آلي، وقيمة غير المعتمدة → يتوقف ويوقف الكتابة."""
    svc, classes = loaded
    run = svc.plan(classes[602598], date(2026, 11, 1))
    first, second = run.proposals.select_related("lesson").order_by("lesson__position")[:2]
    DateProposal.objects.filter(pk__in=[first.pk, second.pk]).update(status=DateProposal.Status.APPROVED)
    log = svc.apply(run, lambda: FakeClient(saved=("", "")))  # الحفظ لم يثبت
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, second.status) == ("failed", "approved") and not log.ok
    assert log.summary["not_attempted"] == 1 and not safety.state().halted
    DateProposal.objects.filter(pk=first.pk).update(status=DateProposal.Status.APPROVED)
    svc.apply(run, lambda: FakeClient(saved=("2027-01-01", "1")))  # المنصة حفظت غير المعتمد
    first.refresh_from_db()
    assert first.status == "failed" and "غير مطابقة" in first.error
    assert safety.state().halted and "كتابة خاطئة" in safety.state().reason
