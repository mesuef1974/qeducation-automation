"""حزمة التحضير الأسبوعية - الخدمة: من الخطة والدروس إلى مجلد الأسبوع، بعميل وهمي (بلا منصة ولا Word)."""
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from neo.domain.bidi import LRM
from neo.domain.types import FileLink, ParsedLesson, ParsedSection, ParsedSlot
from neo.infrastructure import docx_prep
from neo.infrastructure.parsers import parse_date_label
from neo.models import PlatformAssessment, SyncRun
from neo.services.prep_service import MESSAGE_FILE, PackStopped, PrepService
from neo.services.sync_service import SyncService

FIX = Path(__file__).parent / "fixtures"
SNAP = json.loads((FIX / "lessons_snapshot.json").read_text(encoding="utf-8"))
LMS = 602728
W = docx_prep.W_NS

DOC = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>خطة التحضير اليومية العام الدراسي 20</w:t></w:r><w:r><w:t>24 / 2025</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:pPr><w:rPr><w:b/></w:rPr></w:pPr><w:r><w:rPr><w:b/><w:rtl/></w:rPr><w:t>اسم المعلم</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>معلم سابق</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>{{unit}}</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">اليوم </w:t></w:r><w:r><w:t>و التاريخ</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:sdt><w:sdtContent><w:r><w:t>&#x200F;</w:t></w:r></w:sdtContent></w:sdt></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>يوجه المعلم الطلاب لحل تدريب 7 صفحة 151 كتاب الطالب</w:t></w:r></w:p>
<w:p><w:r><w:t>الأهداف: يحدد فترات التزايد 2024</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t xml:space="preserve">الشعبة </w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>اليوم</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>التاريخ</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>الحصة</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
FOOTER = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W}"><w:p><w:r><w:t>خطة التحضير - العام الدراسي 2024-2025</w:t></w:r></w:p>
<w:p><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>2024 – </w:t></w:r><w:r><w:t>2025</w:t></w:r></w:p></w:txbxContent></w:pict></w:r></w:p></w:ftr>"""
COVER = """<?xml version="1.0" encoding="UTF-8"?>
<CoverPageProperties xmlns="http://schemas.microsoft.com/office/2006/coverPageProps">
<PublishDate>العام الدراسي 2024-2025</PublishDate><Abstract/></CoverPageProperties>"""
WORKSHEET = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>ورقة عمل الدوال المتزايدة والمتناقصة   --/</w:t></w:r>
<w:r><w:t>11/2024</w:t></w:r></w:p><w:p><w:r><w:t>السؤال 1</w:t></w:r></w:p></w:body></w:document>"""


def make_docx(path: Path, document: str, footer: str = FOOTER, cover: str | None = COVER) -> bytes:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", document)
        z.writestr("word/footer1.xml", footer)
        if cover:
            z.writestr("customXml/item1.xml", cover)
    return path.read_bytes()


def prep_doc(unit="الوحدة / المحور / المجال", content_year=True):
    doc = DOC.replace("{unit}", unit)
    return doc if content_year else doc.replace(" فترات التزايد 2024", " فترات التزايد")


FIELDS = docx_prep.PrepFields(2026, "معلم الرياضيات", "الأحد", date(2026, 11, 8), "12/2", 5)


def cells(path: Path) -> list[list[str]]:
    from lxml import etree
    root = etree.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    return [[docx_prep.text_of(tc) for tc in tr.iter(docx_prep.w("tc"))] for tr in root.iter(docx_prep.w("tr"))]


# ---------------------------------------------------------------- تعديل الوورد

def test_prepare_docx(tmp_path):
    src = tmp_path / "src.docx"
    original = make_docx(src, prep_doc())
    out = tmp_path / "out.docx"
    res = docx_prep.prepare_docx(src, out, FIELDS)
    assert src.read_bytes() == original  # الأصل لا يُمس
    assert res.teacher and res.date and res.follow_up and res.template == "الخطة اليومية"
    rows = cells(out)
    assert rows[0][0] == "خطة التحضير اليومية العام الدراسي 2026 / 2027"  # الرقم موزّع على عقدتين
    assert rows[1] == ["اسم المعلم", "معلم الرياضيات"]
    assert rows[3][1] == "‏الأحد 8/11/2026"  # عنصر التاريخ الفارغ يبقى، والنص بعده بتنسيق خلية العنوان
    assert rows[-1] == ["12/2", "الأحد", "8/11/2026", "5"]
    z = zipfile.ZipFile(out)
    assert "2026-2027" in z.read("word/footer1.xml").decode() and "2026 – " in z.read("word/footer1.xml").decode()
    assert "2026-2027" in z.read("customXml/item1.xml").decode()  # التذييل المربوط يُعاد منها عند الفتح
    assert "يحدد فترات التزايد 2024" in z.read("word/document.xml").decode()  # المحتوى لا يُمس (عام منفرد)
    assert docx_prep.stale_years(out) == ["word/document.xml: الأهداف: يحدد فترات التزايد 2024"]
    # حتمي: التشغيل الثاني من الأصل نفسه ينتج البايتات نفسها
    again = tmp_path / "again.docx"
    docx_prep.prepare_docx(src, again, FIELDS)
    assert again.read_bytes() == out.read_bytes()


def test_prepare_docx_lesson_plan_template_and_old_date(tmp_path):
    doc = prep_doc("الوحدة").replace("<w:sdt><w:sdtContent><w:r><w:t>&#x200F;</w:t></w:r></w:sdtContent></w:sdt>",
                                     "<w:sdt><w:sdtContent><w:r><w:t>الخميس 05/11/2023</w:t></w:r></w:sdtContent></w:sdt>")
    src = tmp_path / "src.docx"
    make_docx(src, doc, cover=None)
    res = docx_prep.prepare_docx(src, tmp_path / "out.docx", FIELDS)
    assert res.template == "خطة درس"
    assert cells(tmp_path / "out.docx")[3][1] == "الأحد 8/11/2026"  # تاريخ قديم في عنصر التاريخ يُحذف


def test_worksheet_date(tmp_path):
    src = tmp_path / "ws.docx"
    make_docx(src, WORKSHEET, cover=None)
    res = docx_prep.prepare_docx(src, tmp_path / "out.docx", FIELDS, worksheet=True)
    assert res.worksheet_dates == 1 and not res.teacher
    for raw in ("-----11-2024", "----11-2024", "__/__/2025", "../11/2024", "--/11/2024"):
        assert docx_prep.INCOMPLETE_DATE.fullmatch(raw), raw
    assert not docx_prep.INCOMPLETE_DATE.search("صفحة 151-2024") and not docx_prep.INCOMPLETE_DATE.search("2024-2025")
    text = zipfile.ZipFile(tmp_path / "out.docx").read("word/document.xml").decode()
    assert "8/11/2026" in text and "--/" not in text and docx_prep.stale_years(tmp_path / "out.docx") == []


# ---------------------------------------------------------------- القالبان الحقيقيان (ملفان من المنصة، بلا أسماء)

def paras(path: Path) -> list[str]:
    from lxml import etree
    with zipfile.ZipFile(path) as z:
        return [docx_prep.text_of_own(p) for p in etree.fromstring(z.read("word/document.xml")).iter(docx_prep.w("p"))]


@pytest.mark.parametrize("name,template,fields,date_cell", [
    ("prep_lesson_plan.docx", "خطة درس", FIELDS, "الأحد 8/11/2026"),
    ("prep_daily_plan.docx", "الخطة اليومية",
     docx_prep.PrepFields(2026, "معلم الرياضيات", "الاثنين", date(2026, 11, 9), "12/2", 2), "\u200f الاثنين 9/11/2026"),
])
def test_real_templates(tmp_path, name, template, fields, date_cell):
    """كما في المجلد اليدوي W011 بالنص: العام في كل الأجزاء، والرأس، والمتابعة، والمحتوى كما هو."""
    src = FIX / name
    before = paras(src)
    out = tmp_path / name
    res = docx_prep.prepare_docx(src, out, fields)
    assert res.template == template and res.teacher and res.date and res.follow_up and res.years >= 1
    rows = cells(out)
    teacher_row = next(r for r in rows if r and r[0].strip() == "المادة الدراسية")
    assert teacher_row[-1] == "معلم الرياضيات"
    assert next(r for r in rows if len(r) > 3 and r[2].replace(" ", "") == "اليوموالتاريخ")[3] == date_cell
    follow = next(i for i, r in enumerate(rows) if r and r[0].strip() == "الشعبة")
    assert [c.strip() for c in rows[follow + 1][:4]] == [fields.section, fields.day_name, f"{fields.day.day}/11/2026",
                                                        str(fields.period)]
    assert docx_prep.stale_years(out) == []
    after = paras(out)
    assert len(after) == len(before)
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert all("2026" in b or "معلم الرياضيات" in b or b in ("12/2", fields.day_name, str(fields.period)) for _, b in changed)
    assert len(changed) <= 8  # العام، والمعلم، والتاريخ، وخلايا المتابعة فقط
    again = tmp_path / "again.docx"
    docx_prep.prepare_docx(src, again, fields)
    assert again.read_bytes() == out.read_bytes()


def test_real_lesson_plan_footer_and_cover(tmp_path):
    """قالب «خطة درس»: التذييل مربوط بخصائص الغلاف؛ يُعدَّلان معًا وإلا أعاد Word القديم عند الفتح."""
    out = tmp_path / "out.docx"
    docx_prep.prepare_docx(FIX / "prep_lesson_plan.docx", out, FIELDS)
    z = zipfile.ZipFile(out)
    assert "2026-2027" in z.read("word/footer1.xml").decode("utf-8")
    cover = next(n for n in z.namelist() if docx_prep._is_custom_item(n) and b"CoverPageProperties" in z.read(n))
    assert "العام الدراسي 2026-2027" in z.read(cover).decode("utf-8")


def test_real_worksheet_dashes(tmp_path):
    out = tmp_path / "ws.docx"
    fields = docx_prep.PrepFields(2026, "", "الثلاثاء", date(2026, 11, 10), "12/2", 3)
    res = docx_prep.prepare_docx(FIX / "worksheet_dashes.docx", out, fields, worksheet=True)
    assert res.worksheet_dates == 1 and not res.teacher
    assert any(t.strip().endswith("10/11/2026") for t in paras(out)) and docx_prep.stale_years(out) == []


# ---------------------------------------------------------------- الخدمة

@pytest.fixture
def klass(classes):
    k = classes[LMS]
    lessons = []
    for i, (title, label) in enumerate(SNAP[str(LMS)], 1):
        d, p = parse_date_label(label, "2026-2027") if label else (None, None)
        lessons.append(ParsedLesson(LMS * 1000 + i, i, title, "", d, p))
    svc = SyncService()
    svc.ingest(k, lessons, [ParsedSlot(w, p) for w, p in SNAP["timetables"][str(LMS)]])
    svc.plan(k, date(2026, 11, 1))  # رموز المطابقة
    for pos in range(49, 55):
        PlatformAssessment.objects.create(klass=k, lms_assignment_id=900 + pos, title=f"تقييم ختامي - {pos}",
                                          lms_lesson_id=LMS * 1000 + pos, fetched_at="2026-11-01T00:00Z")
    return k


class FakeClient:
    """ملاحظات كل درس: تحضير وعرض، وورقة عمل لكل درس عدا 49، وقسم عرض واحد."""

    def __init__(self, blobs):
        self.blobs, self.downloads = blobs, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def lesson_notes_files(self, lms, lid):
        pos = lid - LMS * 1000
        links = [FileLink(lid, f"/files/{lid}/lkht.docx?lmsauth=a", f"الخطة اليومية : درس {pos}", "lkht", "docx"),
                 FileLink(lid, f"/files/{lid}/rd.pptx?lmsauth=a", f"العرض التقديمي {pos}", "rd", "pptx")]
        if pos != 49:
            links.append(FileLink(lid, f"/files/{lid}/wrq_ml.docx?lmsauth=a", "ورقة عمل التهيئة",
                                  "wrq_ml", "docx"))
        return links, "<html/>"

    def section_files(self, lms, lid, keep=None):
        link = FileLink(lid * 10 + 4, f"/files/{lid * 10 + 4}/sec.pptx?lmsauth=a", "عرض تقديمي : أجد القيم الحرجة.",
                        "sec", "pptx")
        return [(ParsedSection(1, "العرض 1", "powerpoint"), [link])]

    def download(self, url, path):
        kind = url.split("/")[3].split(".")[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.blobs[kind])
        self.downloads += 1
        return len(self.blobs[kind])


@pytest.fixture
def blobs(tmp_path):
    return {"lkht": make_docx(tmp_path / "p.docx", prep_doc(content_year=False)), "wrq_ml": make_docx(tmp_path / "w.docx", WORKSHEET, cover=None),
            "rd": b"PK-pptx", "sec": b"PK-section"}


def test_prep_pack_week_11(klass, blobs, tmp_path):
    policy = {"dest_dir": tmp_path / "Desktop", "cache_dir": tmp_path / "cache", "word_check": False,
              "teacher": "معلم الرياضيات"}
    client = FakeClient(blobs)
    run = PrepService(policy).run(klass, 11, lambda: client)
    s = run.summary
    assert run.ok and run.kind == SyncRun.Kind.PREP, s["errors"]
    week_dir = tmp_path / "Desktop" / "W011 - 12-2"
    assert s["folder"] == str(week_dir)
    assert [x["position"] for x in s["lessons"]] == [49, 50, 51, 52, 53, 54]
    assert [(x["date"], x["period"]) for x in s["lessons"]] == [
        ("2026-11-08", 5), ("2026-11-09", 2), ("2026-11-10", 3), ("2026-11-10", 5), ("2026-11-11", 4), ("2026-11-12", 6)]
    first = week_dir / "49 - الدوال المتزايدة والمتناقصة 2"
    assert sorted(p.name for p in first.iterdir()) == [
        "التحضير - الخطة اليومية   درس 49.docx", "عرض الدرس - العرض التقديمي 49.pptx", "عروض الأقسام"]
    assert (first / "عروض الأقسام" / "1 - العرض 1.pptx").read_bytes() == b"PK-section"
    assert s["lessons"][0]["missing"] == ["ورقة العمل"] and s["lessons"][1]["missing"] == []
    assert cells(first / "التحضير - الخطة اليومية   درس 49.docx")[-1] == ["12/2", "الأحد", "8/11/2026", "5"]
    ws = week_dir / "52 - القيم القصوى للدوال 1" / "ورقة عمل - ورقة عمل التهيئة.docx"
    assert "10/11/2026" in zipfile.ZipFile(ws).read("word/document.xml").decode()
    msg = (week_dir / MESSAGE_FILE).read_text(encoding="utf-8-sig").splitlines()
    assert msg[1].split("\t")[:3] == ["12/2", f"الدوال المتزايدة والمتناقصة ({LRM}2–4)، القيم القصوى للدوال ({LRM}1–3)",
                                      f"{LRM}144–163"]
    assert "ص151: 7" in s["message"]["row"][3] and "(6)" in s["message"]["row"][3]
    assert s["message"]["row"][4] == "لا يوجد"
    assert s["stale_years"] == {}
    assert client.downloads == 6 * 4 - 1 and s["same_as_previous"] is None

    # تشغيل ثانٍ: من الذاكرة المؤقتة بلا تنزيل، والملفات نفسها بايتًا ببايت
    again = PrepService(policy).run(klass, 11, lambda: client)
    assert client.downloads == 23 and again.summary["downloads"] == 0
    assert again.summary["same_as_previous"] is True and again.summary["hashes"] == s["hashes"]


def test_prep_pack_stops_without_guessing(klass, blobs, tmp_path):
    policy = {"dest_dir": tmp_path, "cache_dir": tmp_path / "cache", "word_check": False}
    with pytest.raises(PackStopped, match="المشتقات من الرتب العليا 4"):
        PrepService(policy).run(klass, 10, lambda: FakeClient(blobs))
    run = SyncRun.objects.get(kind=SyncRun.Kind.PREP)
    assert not run.ok and "المشتقات" in run.summary["error"]
    assert not list(tmp_path.glob("W0*"))  # لم يُكتب شيء
