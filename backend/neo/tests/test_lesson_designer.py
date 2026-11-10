from datetime import date

from neo.domain import assessment, lesson_spec, review_bank
from neo.services import lesson_designer


def _req():
    return lesson_designer.ReviewRequest(602598, "2026-2027", "الوحدة الثانية", date(2026, 11, 19), 1)


def test_bank_every_mcq_has_four_distinct_choices():
    for it in review_bank.ITEMS:
        if it.choices:
            assert len(it.choices) == 4 and len(set(it.choices)) == 4, it.text
            assert it.work, it.text
    assert {i.skill for i in review_bank.ITEMS} == set(review_bank.SKILLS)


def test_quiz_rotates_answers_and_roundtrips():
    qs = review_bank.review_quiz()
    assert len({q.correct for q in qs if q.type == assessment.MCQ}) > 1
    assert assessment.parse_text(assessment.to_text(qs)) == qs


def test_design_writes_valid_spec(tmp_path):
    path = lesson_designer.design(_req(), tmp_path / "r")
    spec = lesson_spec.load(path)
    assert spec.title == "مراجعة واختبار الوحدة الثانية"
    assert len(spec.quiz) == len(review_bank.review_quiz())
    assert {n.label.split(" - ")[0] for n in spec.notes} == {"التحضير", "ورقة عمل", "عرض الدرس"}
    for n in spec.notes:
        assert n.path.stat().st_size > 1000
    assert lesson_designer.design(_req(), tmp_path / "r") == path  # إعادة آمنة
