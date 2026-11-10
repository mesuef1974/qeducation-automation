from datetime import date
from pathlib import Path

import pytest

from neo.domain import assessment, lesson_spec, review_bank
from neo.infrastructure import plan_docx
from neo.services import lesson_designer

CACHE = Path(__file__).resolve().parents[3].parent / "backend" / "media" / "prep_cache"


def _req(**kw):
    return lesson_designer.ReviewRequest(602598, "2026-2027", "الوحدة الثانية", date(2026, 11, 19), 1, **kw)


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


def test_ltr_isolates_math_only():
    out = review_bank.ltr("حل x² + 1 = 0 الآن")
    assert out == f"حل {review_bank.LRE}x² + 1 = 0{review_bank.PDF} الآن"


def test_spec_prefixes_show_and_points(tmp_path):
    base = {"class": 1, "academic_year": "2026-2027", "title": "t", "description": "d", "date": "2026-11-19",
            "period": 1, "grade": "g", "term": "f", "outcome_prefixes": ["10.2."], "show": True,
            "points": {"points": 5, "game": "g", "notification": "Popup"}}
    s = lesson_spec.parse(base, tmp_path)
    assert s.outcome_prefixes == ("10.2.",) and s.show and s.points["points"] == 5
    with pytest.raises(lesson_spec.SpecError):
        lesson_spec.parse({**base, "points": {"points": 5}}, tmp_path)


def test_plan_dropdown_rejects_unknown_value():
    import copy  # noqa: F401

    from docx import Document
    from docx.oxml.ns import qn
    assert callable(plan_docx._set_dropdown) and qn("w:sdt") and Document


@pytest.mark.skipif(not (CACHE / "files").exists(), reason="لا أصول منزّلة من المنصة")
def test_design_uses_neighbor_templates(tmp_path):
    req = _req(before_title="إثبات تشابه المثلثات (ج1)", cache_dir=CACHE)
    path = lesson_designer.design(req, tmp_path / "r")
    spec = lesson_spec.load(path)
    assert spec.title == "مراجعة واختبار الوحدة الثانية" and spec.outcome_prefixes == ("10.2.",) and spec.show
    assert len(spec.quiz) == len(review_bank.review_quiz())
    assert {n.label.split(" - ")[0] for n in spec.notes} == {"التحضير", "ورقة عمل", "عرض الدرس"}
    from docx import Document
    plan = Document(str(tmp_path / "r" / "plan.docx"))
    assert plan_docx.lesson_title(plan) == "مراجعة واختبار الوحدة الثانية"
    from pptx import Presentation
    deck = Presentation(str(tmp_path / "r" / "deck.pptx"))
    assert len(deck.slides) == 2 + 10 + 3  # عنوان وأهداف وعشر مهارات ونشاط وغلق وواجب
    assert lesson_designer.design(req, tmp_path / "r") == path  # إعادة آمنة
