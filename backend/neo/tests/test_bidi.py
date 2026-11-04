"""اتجاه الأرقام في النص العربي: النطاقات والعام وأرقام التدريبات ذات الحرف اللاتيني."""
from neo.domain.bidi import LRM, RLM, fix_ranges, latin_item, ltr


def test_fix_ranges_marks_glued_ranges_only():
    title = "الرياضيات - المستوى 10 - 2026-2027 ف1"
    assert fix_ranges(title) == f"الرياضيات - المستوى 10 - {LRM}2026-2027 ف1"  # «10 - 2026» ليس نطاقًا
    assert fix_ranges(fix_ranges(title)) == fix_ranges(title)
    assert fix_ranges("الدروس 49–54") == f"الدروس {LRM}49–54" and fix_ranges("بلا أرقام") == "بلا أرقام"


def test_latin_item_and_ltr():
    assert latin_item("17a") == f"17a{RLM}" and latin_item("18") == "18"
    assert ltr("+25.3") == f"{LRM}+25.3"
