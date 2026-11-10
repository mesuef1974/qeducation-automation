"""بناء درس جديد كامل: المواصفة النقية، وتسلسل الخطوات وإعادة التشغيل والمغلق والتوقف عند أول خطأ؛ بلا منصة."""
import json
from datetime import date

import pytest

from neo.domain import lesson_spec as ls
from neo.infrastructure.client import NotLoggedIn, PlatformError
from neo.services import lesson_build_service as build
from neo.services import safety

QUIZ = "س: كم 2+2؟\n* 4\n- 5\n\nس: الأرض مسطحة\n= خطأ"


def spec_dict(tmp_path, **over):
    (tmp_path / "plan.docx").write_bytes(b"x")
    (tmp_path / "deck.pptx").write_bytes(b"x")
    d = {"class": 602598, "academic_year": "2026-2027", "title": "مراجعة واختبار الوحدة الثانية",
         "description": "مراجعة شاملة.", "date": "2026-11-18", "period": 5, "grade": "الصف العاشر", "term": "الفصل الأول",
         "before_title": "", "tags": ["مراجعة", "الوحدة الثانية"], "outcome_codes": ["2.1"],
         "pages": [{"name": "أهداف الدرس", "html": "<p>أهداف</p>"}],
         "decks": [{"title": "العرض التقديمي - مراجعة", "file": "deck.pptx"}],
         "quiz": QUIZ, "notes": [{"label": "التحضير - خطة المراجعة", "file": "plan.docx"}]}
    d.update(over)
    return d


def test_spec_parses_and_rejects_incomplete(tmp_path):
    s = ls.parse(spec_dict(tmp_path), tmp_path)
    assert s.day == date(2026, 11, 18) and len(s.quiz) == 2 and s.notes[0].path.name == "plan.docx"
    lines = build.describe(s)
    assert "يُنشأ مخفيًا" in lines[0] and any("قسم عرض" in x for x in lines) and any("تقييم" in x for x in lines)
    bad = [({"date": "18-11-2026"}, "YYYY"), ({"period": 9}, "الحصة"), ({"title": ""}, "عنوان"),
           ({"notes": [{"label": "ملف عشوائي", "file": "plan.docx"}]}, "يبدأ بدوره"),
           ({"decks": [{"title": "x", "file": "غير_موجود.pptx"}]}, "غير موجود"),
           ({"tags": [str(i) for i in range(9)]}, "الكلمات"),
           ({"pages": [{"name": "أ", "html": "x"}], "decks": [{"title": "أ", "file": "deck.pptx"}]}, "مكررة")]
    for over, msg in bad:
        with pytest.raises(ls.SpecError, match=msg):
            ls.parse(spec_dict(tmp_path, **over), tmp_path)


def test_load_reads_json_file(tmp_path):
    f = tmp_path / "lesson.json"
    f.write_text(json.dumps(spec_dict(tmp_path), ensure_ascii=False), encoding="utf-8")
    assert ls.load(f).title == "مراجعة واختبار الوحدة الثانية"
    with pytest.raises(ls.SpecError, match="تعذّرت"):
        ls.load(tmp_path / "لا_يوجد.json")


class Fake:
    """عميل وهمي بحالة المنصة: ما يُكتب يبقى، فيُختبر استكمال الانقطاع بلا تكرار."""

    def __init__(self, existing=None, locked=False, fail_on=None):
        self.lessons = dict(existing or {})  # عنوان ← معرّف
        self.tags, self.outcomes, self.sections, self.quizzes, self.notes = {}, {}, {}, {}, {}
        self.shown, self.locked, self.fail_on, self.calls = {}, locked, fail_on, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _do(self, name):
        self.calls.append(name)
        if self.fail_on == name:
            raise PlatformError(f"عطل في {name}")

    def find_lesson_id(self, lms, title, year):
        return self.lessons.get(title)

    def create_lesson(self, lms, title, desc, year, when, before):
        self._do("create")
        if title in self.lessons:
            return self.lessons[title], False
        self.lessons[title] = 900 + len(self.lessons)
        self.shown[self.lessons[title]] = False
        return self.lessons[title], True

    def lesson_is_open(self, lms, lid):
        return not self.locked

    def lesson_tags(self, lms, lid):
        return self.tags.get(lid, [])

    def set_lesson_tags(self, lms, lid, tags):
        self._do("tags")
        self.tags[lid] = tags

    def outcomes_html(self, lms, lid):
        return "".join(f'<span class="proficiencyItem"><a href="/x">{c}. نص</a></span>' for c in self.outcomes.get(lid, []))

    def available_outcomes(self, lms, lid):
        return [{"id": 5, "code": "2.1", "text": "ن"}]

    def link_outcomes(self, lms, lid, ids):
        self._do("outcomes")
        self.outcomes[lid] = ["2.1"]

    def section_names(self, lms, lid):
        return self.sections.get(lid, [])

    def add_page_section(self, lms, lid, name, html):
        self._do("page")
        self.sections.setdefault(lid, []).append(name)

    def add_file_section(self, lms, lid, path, title, grade, term):
        self._do("deck")
        self.sections.setdefault(lid, []).append(title)

    def assessment_names(self, lms, lid):
        return self.quizzes.get(lid, [])

    def add_quiz(self, lms, lid, name, questions):
        self._do("quiz")
        self.quizzes.setdefault(lid, []).append(name)

    def add_notes_files(self, lms, lid, files):
        self._do("notes")
        self.notes[lid] = [label for _, label in files]

    def lesson_shown(self, lms, lid):
        return self.shown.get(lid, True)


def run(tmp_path, client, classes, **over):
    s = ls.parse(spec_dict(tmp_path, **over), tmp_path)
    return build.LessonBuildService().build(s, lambda: client)


def test_builds_everything_in_order_hidden(tmp_path, classes):
    c = Fake()
    r = run(tmp_path, c, classes)
    assert r.ok and r.summary["lesson"] == 900 and not r.summary["stopped"]
    assert c.calls == ["create", "tags", "outcomes", "page", "deck", "quiz", "notes"]
    assert c.shown[900] is False and c.notes[900] == ["التحضير - خطة المراجعة"]


def test_rerun_is_idempotent(tmp_path, classes):
    c = Fake()
    run(tmp_path, c, classes)
    c.calls.clear()
    r = run(tmp_path, c, classes)
    assert r.ok and c.calls == ["create", "notes"]  # الإنشاء يعيد الموجود، والملاحظات تتحقق ولا ترفع مرتين
    assert all(s["state"] in {"موجود", "موجودة", "اكتملت"} for s in r.summary["steps"])


def test_resumes_after_failure_without_duplicating(tmp_path, classes):
    c = Fake(fail_on="deck")
    r = run(tmp_path, c, classes)
    assert not r.ok and "عطل في deck" in r.summary["stopped"] and c.sections[900] == ["أهداف الدرس"]
    c.fail_on = None
    r2 = run(tmp_path, c, classes)
    assert r2.ok and c.sections[900] == ["أهداف الدرس", "العرض التقديمي - مراجعة"] and c.quizzes[900] == ["تقييم الدرس"]


def test_locked_existing_lesson_is_not_written(tmp_path, classes):
    c = Fake(existing={"مراجعة واختبار الوحدة الثانية": 777}, locked=True)
    r = run(tmp_path, c, classes)
    assert not r.ok and safety.LOCKED_SKIP in r.summary["stopped"] and c.calls == ["create"]


def test_unknown_outcome_stops_and_halted_writes_refuse(tmp_path, classes):
    r = run(tmp_path, Fake(), classes, outcome_codes=["9.9"])
    assert not r.ok and "9.9" in r.summary["stopped"]
    s = safety.state()
    s.halted, s.reason = True, "اختبار"
    s.save()
    with pytest.raises(safety.WritesHalted):
        run(tmp_path, Fake(), classes)


def test_session_loss_raises_and_unknown_class(tmp_path, classes):
    class Lost(Fake):
        def create_lesson(self, *a):
            raise NotLoggedIn("انتهت الجلسة")

    with pytest.raises(NotLoggedIn):
        run(tmp_path, Lost(), classes)
    with pytest.raises(build.BuildError, match="غير مسجّل"):
        run(tmp_path, Fake(), classes, **{"class": 111})
