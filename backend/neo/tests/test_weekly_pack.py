"""حزمة التحضير الأسبوعية - الدومين: أجزاء الأسبوع من الخطة، والربط بدروس المنصة، والتوزيع على الحصص،
وأسماء الملفات، وصف الرسالة الأسبوعية. بلا Django ولا منصة."""
from datetime import date

import pytest

from neo.domain import weekly_pack as wp
from neo.domain.bidi import LRM, RLM
from neo.domain.types import FileLink
from neo.services.scheduling import WeekSpan

INC, EXT, HIGH = "الدوال المتزايدة والمتناقصة", "القيم القصوى للدوال", "المشتقات من الرتب العليا"
# بنود الخطة الحقيقية للصف 12 (الأسابيع 8-12، والأسبوع 9 إجازة)
ENTRIES = [
    wp.PlanEntry(8, 1, "2.8", "الاشتقاق الضمني", 3),
    wp.PlanEntry(10, 1, "2.9", HIGH, 4),
    wp.PlanEntry(10, 2, "مراجعة واختبار وحدة#2", "مراجعة واختبار الوحدة الثانية", 1, is_lesson=False),
    wp.PlanEntry(10, 3, "3.1", INC, 1),
    wp.PlanEntry(11, 1, "3.1", INC, 3),
    wp.PlanEntry(11, 2, "3.2", EXT, 3),
    wp.PlanEntry(12, 1, "3.2", EXT, 1),
]
# دروس المنصة للصف 12/2 كما هي (المسافات المزدوجة و«و المتناقصة» من المنصة)، وتواريخها تسبق الخطة بدرسين
TITLES = {45: f"{HIGH} 1", 46: f"{HIGH} 2", 47: f"{HIGH} 3", 48: "الدوال المتزايدة و المتناقصة 1",
          49: "الدوال المتزايدة و المتناقصة 2", 50: f"{INC} 3", 51: f"{INC} 4", 52: "القيم القصوى  للدوال 1",
          53: "القيم القصوى  للدوال 2", 54: "القيم القصوى  للدوال 3", 55: "القيم القصوى  للدوال 4"}
CODES = {45: "2.9", 46: "2.9", 47: "2.9", 48: "3.1", 49: "3.1", 50: "3.1", 51: "3.1",
         52: "3.2", 53: "3.2", 54: "3.2", 55: "3.2"}
PLATFORM_DATES = {49: (date(2026, 11, 4), 4), 50: (date(2026, 11, 5), 6), 51: (date(2026, 11, 8), 5),
                  52: (date(2026, 11, 9), 2), 53: (date(2026, 11, 10), 3), 54: (date(2026, 11, 10), 5)}
TIMETABLE_12_2 = [(6, 5), (0, 2), (1, 3), (1, 5), (2, 4), (3, 6)]
WEEK_11 = WeekSpan(11, date(2026, 11, 8), True)


def lessons(with_codes=True):
    return [wp.LessonRef(17955800 + pos, pos, t, CODES[pos] if with_codes else "", *PLATFORM_DATES.get(pos, (None, None)))
            for pos, t in TITLES.items()]


def test_week_parts_subtract_previous_weeks():
    parts = [(e.code, p) for e, p in wp.week_parts(ENTRIES, 11)]
    assert parts == [("3.1", 2), ("3.1", 3), ("3.1", 4), ("3.2", 1), ("3.2", 2), ("3.2", 3)]
    assert [(e.code, p) for e, p in wp.week_parts(ENTRIES, 12)] == [("3.2", 4)]


@pytest.mark.parametrize("with_codes", [True, False])
def test_select_week_11(with_codes):
    """معيار القبول: ستة دروس (49–54) في 8–12/11/2026 والحصص 5، 2، 3، 5، 4، 6 - بالرمز أو بالعنوان وحده."""
    pack = wp.select_week(ENTRIES, lessons(with_codes), WEEK_11, TIMETABLE_12_2)
    assert [pl.position for pl in pack] == [49, 50, 51, 52, 53, 54]
    assert [pl.date.day for pl in pack] == [8, 9, 10, 10, 11, 12]
    assert [pl.period for pl in pack] == [5, 2, 3, 5, 4, 6]
    assert [pl.day_name for pl in pack] == ["الأحد", "الاثنين", "الثلاثاء", "الثلاثاء", "الأربعاء", "الخميس"]
    assert pack[0].date_text == "8/11/2026"
    assert pack[0].folder == "49 - الدوال المتزايدة والمتناقصة 2"
    assert pack[3].folder == "52 - القيم القصوى للدوال 1"
    assert all(pl.platform_differs for pl in pack)  # تواريخ المنصة تسبق الخطة بدرسين


def test_missing_part_stops():
    """الأسبوع 10: المشتقات من الرتب العليا 4 حصص في الخطة و3 دروس فقط على المنصة."""
    with pytest.raises(wp.PackError) as err:
        wp.select_week(ENTRIES, lessons(), WeekSpan(10, date(2026, 11, 1), True), TIMETABLE_12_2)
    assert f"{HIGH} 4" in str(err.value) and err.value.details["missing"][0] == f"{HIGH} 4"


def test_count_mismatch_stops():
    """يوم إجازة داخل الأسبوع: ست دروس وخمس حصص، فلا تخمين."""
    with pytest.raises(wp.PackError) as err:
        wp.select_week(ENTRIES, lessons(), WEEK_11, TIMETABLE_12_2, {date(2026, 11, 9)})
    assert err.value.details["slots"] == 5 and err.value.details["plan_periods"] == 6
    assert "(6)" in str(err.value) and "(5)" in str(err.value)


def test_break_week_stops():
    with pytest.raises(wp.PackError, match="إجازة"):
        wp.select_week(ENTRIES, lessons(), WeekSpan(9, date(2026, 10, 25), False), TIMETABLE_12_2)


@pytest.mark.parametrize("title,part", [
    ("القيم القصوى  للدوال 3", 3), ("رسم منحنيات الدوال ج2", 2), ("الاتصال(2)", 2), ("إثبات (ج1)", 1),
    ("مراجعة الوحدة", 1),
])
def test_lesson_part(title, part):
    assert wp.lesson_part(title) == part


def test_topic_key():
    assert wp.topic_key("الدوال المتزايدة و المتناقصة 2") == wp.topic_key(INC)
    assert wp.topic_key("القيم القصوى  للدوال 1") == wp.topic_key(EXT)
    assert wp.topic_key("رسم منحنيات الدوال ج1") == wp.topic_key("رسم منحنيات الدوال")


def link(stem, ext, name):
    return FileLink(1, f"/files/1/{stem}.{ext}?lmsauth=ab", name, stem, ext)


def test_file_names():
    """كما في المجلد اليدوي: المحرف الممنوع في ويندوز يصير مسافة."""
    prep = link("lkht_lywmy", "docx", "الخطة اليومية : الدوال المتزايدة والمتناقصة 3")
    ws = link("wrq_ml_lthy", "docx", "ورقة عمل التهيئة")
    pres = link("rd_tqdymy", "pptx", "العرض التقديمي -الدوال المتزايدة والمتناقصة 3.pptx")
    assert [wp.note_role(x) for x in (prep, ws, pres)] == ["prep", "worksheet", "presentation"]
    assert wp.note_role(link("mrj_1", "docx", "x")) == "worksheet"
    # اسم مرمّز آخر لكن عنوان الرابط «ورقة عمل…»: ورقة عمل لا تحضير (دروس 58 و59 في 12/2)
    odd = link("mrj_mtwsT", "docx", "ورقة عمل التهيئة")
    assert wp.note_role(link("lkht_x", "docx", "ورقة عمل التهيئة")) == "worksheet"
    assert wp.note_role(odd) == "worksheet"
    assert wp.note_file_name(prep) == "التحضير - الخطة اليومية   الدوال المتزايدة والمتناقصة 3.docx"
    assert wp.note_file_name(ws) == "ورقة عمل - ورقة عمل التهيئة.docx"
    assert wp.note_file_name(pres) == "عرض الدرس - العرض التقديمي -الدوال المتزايدة والمتناقصة 3.pptx"
    sec = link("x", "pptx", "رابط العرض")
    # اسم القسم في الدرس كما في المجلد اليدوي، بنقطته الأخيرة؛ والمحرف الممنوع مسافة
    assert wp.section_file_name(1, "عرض تقديمي  إيجاد فترات التزايد باستعمال اختبار المشتقة الأولى.", sec) == \
        "1 - عرض تقديمي  إيجاد فترات التزايد باستعمال اختبار المشتقة الأولى..pptx"
    assert wp.section_file_name(2, "العرض التقديمي :-   أحدد القيم", sec) == "2 - العرض التقديمي  -   أحدد القيم.pptx"
    assert wp.section_file_name(3, " ", sec) == "3 - رابط العرض.pptx"
    assert wp.safe_name('a/b\\c?*') == "a b c" and wp.safe_name("...") == "ملف"
    assert wp.week_folder("W{week:03d} - {section}", 11, "12/2") == "W011 - 12-2"
    assert wp.class_section("الرياضيات 12/2") == "12/2"


def test_message_row():
    pack = wp.select_week(ENTRIES, lessons(), WEEK_11, TIMETABLE_12_2)
    book = wp.book_for(12, 1, "العلمي والتكنولوجي")
    assert wp.week_pages(book, pack) == (f"{LRM}144–163", [])
    assert wp.week_pages(None, pack) == ("", ["3.1", "3.2"])
    assert wp.book_for(10, 1, "") is None
    texts = [
        "يوجه المعلم الطلاب لحل تدريب 20a صفحة 151 كتاب الطالب مستخدمين استراتيجية الحل الفردي",
        "يعرض المعلم لتدريب رقم  4 صفحة 66 دليل التقويم  العرض التقديمي",
        "أوجه الطلاب  إلى حل تمرين 6 ص 151 بشكل فردي", "الواجب صفحة 151 رقم 19و20",
        "يوجه المعلم الطلاب لحل تدريب 6 صفحة 166 كتاب الطالب", "الطالب سريع الإنجاز  يقدم له تدريب 7  صفحة 151",
    ]
    ex = wp.book_exercises(texts)
    assert ex == {151: ["20a", "6", "19", "20", "7"], 166: ["6"]}
    hw = wp.homework_text(ex, 6)
    assert hw == f"تدريبات كتاب الطالب ص151: 6، 7، 19، 20، 20a{RLM}؛ ص166: 6، والتقييم الختامي على المنصة (6)"
    assert wp.homework_text({}, 0) == ""
    assert wp.tests_text([]) == "لا يوجد"
    assert wp.tests_text([("اختبار قصير", date(2026, 11, 10), date(2026, 11, 10))]) == "اختبار قصير (10/11/2026)"
    row = wp.message_row("12/2", pack, "144–163", hw, "لا يوجد")
    assert row[:3] == ["12/2", f"{INC} ({LRM}2–4)، {EXT} ({LRM}1–3)", "144–163"] and row[-1] == ""
    tsv = wp.message_tsv(row).splitlines()
    assert tsv[0].split("\t") == list(wp.MESSAGE_HEADER) and len(tsv[1].split("\t")) == 6


def test_parse_notes_links():
    """صفحة الملاحظات الحقيقية: الرقم مجلد يتشاركه التحضير والعرض، فلا يُعدّ تكرارًا؛ وصور الصفوف ليست ملفات."""
    from pathlib import Path

    from neo.infrastructure.parsers import parse_file_links
    html = (Path(__file__).parent / "fixtures" / "lesson_notes.html").read_text(encoding="utf-8")
    links = parse_file_links(html)
    assert [(x.file_id, x.ext, x.name) for x in links] == [
        (459472, "docx", "خطة درس - الدوال المتزايدة و المتناقصة 2"),
        (459472, "pptx", "عرض تقديمي - الدوال المتزايدة و المتناقصة 2")]
    assert links[0].key != links[1].key and links[0].url.startswith("/files/459472/") and "lmsauth=" in links[0].url
    assert [wp.note_file_name(x) for x in links] == [
        "التحضير - خطة درس - الدوال المتزايدة و المتناقصة 2.docx",
        "عرض الدرس - عرض تقديمي - الدوال المتزايدة و المتناقصة 2.pptx"]


def test_absent_non_lesson_is_waived_and_keeps_slot_alignment():
    """قرار المعلم 2026-11-09: نشاط غير درسي (مراجعة/اختبار) غائب عن المنصة يُسقَط ولا يوقف الحزمة؛
    وتبقى دروس الأسبوع على حصصها المقابلة بالترتيب."""
    review = wp.PlanEntry(11, 3, "مراجعة واختبار وحدة#3", "مراجعة واختبار الوحدة الثالثة", 1, is_lesson=False)
    timetable = [*TIMETABLE_12_2, (3, 7)]  # حصة سابعة يملؤها نشاط المراجعة المُسقَط
    base = wp.select_week(ENTRIES, lessons(), WEEK_11, TIMETABLE_12_2)
    pack = wp.select_week([*ENTRIES, review], lessons(), WEEK_11, timetable)
    assert [(p.lms_lesson_id, p.date, p.period) for p in pack] == [(p.lms_lesson_id, p.date, p.period) for p in base]
    with pytest.raises(wp.PackError, match="أكثر من حصصه"):  # الزيادة على الحصص تبقى خطأ
        wp.select_week([*ENTRIES, review], lessons(), WEEK_11, TIMETABLE_12_2)


def test_missing_real_lesson_still_stops_the_pack():
    gone = [pl for pl in lessons() if pl.position != 55]
    with pytest.raises(wp.PackError, match="بلا درس على المنصة"):
        wp.select_week(ENTRIES, gone, WeekSpan(12, date(2026, 11, 15), True), TIMETABLE_12_2)


def test_fewer_lessons_than_slots_uses_first_slots():
    """قرار المعلم 2026-11-09: دروس الخطة أقل من حصص الجدول: الدروس على أولى الحصص والزائدة فارغة."""
    base = wp.select_week(ENTRIES, lessons(), WEEK_11, TIMETABLE_12_2)
    pack = wp.select_week(ENTRIES, lessons(), WEEK_11, [*TIMETABLE_12_2, (3, 7)])
    assert [(p.lms_lesson_id, p.date, p.period) for p in pack] == [(p.lms_lesson_id, p.date, p.period) for p in base]
