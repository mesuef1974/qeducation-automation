"""صفحات كتاب الطالب: بيانات الكتابين من دليل المعلم، ونطاق الأسبوع، وتصفية الواجبات بصفحاته."""
from datetime import date
from itertools import pairwise

import pytest

from neo.domain import student_books as sb
from neo.domain import weekly_pack as wp
from neo.domain.bidi import LRM


def pl(code, part, title="", position=1):
    return wp.PackLesson(position, position, title, title or code, code, part, date(2026, 11, 15), 1)


@pytest.mark.parametrize("key", list(sb.BOOKS))
def test_book_entries_are_ordered_and_contiguous_within_a_unit(key):
    """لا تداخل ولا فجوة بين دروس الوحدة الواحدة ومراجعتها؛ وبين الوحدات صفحات الافتتاح والمشروع فقط."""
    entries = sb.BOOKS[key].entries
    assert len({e.key for e in entries}) == len(entries)
    for a, b in pairwise(entries):
        assert a.first <= a.last < b.first
        same_unit = b.key.split(".")[0] == a.key.split(".")[0] or b.key.startswith(sb.REVIEW)
        if same_unit:
            assert b.first == a.last + 1, (a, b)
        else:
            assert 1 < b.first - a.last <= 5, (a, b)  # افتتاح الوحدة ومشروعها


def test_book_key_maps_plan_codes():
    assert sb.book_key("2.10") == "2.10"
    assert sb.book_key("مراجعة واختبار وحدة#2") == "مراجعة#2"
    assert sb.book_key("تهيئة#1") is None and sb.book_key("مشروع STEM#0") is None
    assert sb.book_for(12, 1, "العلمي والتكنولوجي").entry("3.4").first == 180
    assert sb.book_for(11, 1, "العلمي") is None


def test_week_12_pages_12_2():
    """3.2 الجزء 4 بعد نهاية الجزء 3 (163) حتى آخر 3.4 الذي بدأ هذا الأسبوع: نطاق متصل."""
    book = sb.book_for(12, 1, "العلمي والتكنولوجي")
    week = [pl("3.2", 4)] + [pl("3.3", i) for i in range(1, 5)] + [pl("3.4", 1)]
    assert wp.week_ranges(book, week) == ([(164, 191)], [])
    assert wp.week_pages(book, week) == (f"{LRM}164–191", [])


def test_week_12_pages_10_3_with_unit_review_and_gap():
    """الدائرة والمراجعة متصلتان، ثم 3.3 بعد افتتاح الوحدة الثالثة ودرسين لم يُدرَّسا: نطاقان."""
    book = sb.book_for(10, 1, "")
    week = [pl("2.10", 2), pl("2.10", 3), pl("مراجعة واختبار وحدة#2", 1), pl("3.3", 1), pl("3.3", 2)]
    ranges, unknown = wp.week_ranges(book, week)
    assert (ranges, unknown) == ([(105, 121), (142, 149)], [])
    assert wp.pages_text(ranges) == f"{LRM}105–121، {LRM}142–149"


def test_unknown_lesson_is_reported_not_silently_cut():
    book = sb.book_for(12, 1, "العلمي")
    week = [pl("3.6", 1), pl("4.1", 1), pl("تهيئة#1", 1)]
    assert wp.week_ranges(book, week) == ([(204, 214)], ["4.1"])
    assert wp.week_ranges(None, week) == ([], ["3.6", "4.1"])


def test_homework_only_from_week_pages():
    """«ص67» من درس سابق ذُكرت في تحضير الأسبوع 12 فلا تدخل واجباته."""
    inside, outside = wp.within({67: ["3"], 166: ["31", "35"], 189: ["4"]}, [(164, 191)])
    assert inside == {166: ["31", "35"], 189: ["4"]} and outside == {67: ["3"]}


def test_title_mismatch_is_flagged_with_the_book_title():
    book = sb.book_for(10, 1, "")
    week = [pl("2.6", 1, "القانون العام لحل المعادلة التربيعية والمميز"), pl("2.10", 1, "معادلة الدائرة في المستوى الإحداثي")]
    assert wp.title_mismatches(book, week) == [
        {"code": "2.6", "plan": "القانون العام لحل المعادلة التربيعية والمميز",
         "book": "القانون العام لحل المعادلات التربيعية والمميز"}]
