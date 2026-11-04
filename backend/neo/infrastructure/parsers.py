"""تحليل صفحات NEO LMS (HTML) إلى كيانات نقية."""
import re
from datetime import date

from bs4 import BeautifulSoup

from neo.domain.types import FileLink, ParsedAssessment, ParsedLesson, ParsedSection, ParsedSlot, ParsedTile

MONTHS = {m: i for i, m in enumerate(
    ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"], 1)}
WEEKDAYS = {"الإثنين": 0, "الاثنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الاربعاء": 2,
            "الخميس": 3, "الجمعة": 4, "السبت": 5, "الأحد": 6, "الاحد": 6}

_LABEL = re.compile(r"(?P<month>[؀-ۿ]+)\s+(?P<day>\d{1,2})\s*,?\s*(?:الحصة\s*(?:ال)?(?P<period>\d+))?")
_POSITION = re.compile(r"^\s*(\d+)\.\s*")
# شارات بطاقة الدرس في قائمة الدروس
HIDDEN_BADGE, POINTS_BADGE = "شخصى", "يمنح النقاط"


def year_for_month(month: int, academic_year: str) -> int:
    """'2026-2027': أغسطس-ديسمبر في السنة الأولى، يناير-يوليو في الثانية."""
    first, second = (int(y) for y in academic_year.split("-"))
    return first if month >= 8 else second


def parse_date_label(label: str, academic_year: str) -> tuple[date | None, int | None]:
    m = _LABEL.search(label or "")
    if not m or m["month"] not in MONTHS:
        return None, None
    month = MONTHS[m["month"]]
    return date(year_for_month(month, academic_year), month, int(m["day"])), (int(m["period"]) if m["period"] else None)


def parse_lessons(html: str, academic_year: str) -> list[ParsedLesson]:
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for tile in soup.select("#blockView > div.draggable[id]"):
        lesson_id = int(tile["id"])
        if lesson_id in seen:
            continue
        seen.add(lesson_id)
        raw_title = tile.select_one("h2.class_name").get_text(" ", strip=True)
        pos = _POSITION.match(raw_title)
        label = tile.select_one(".label_box_wrap .label.box")
        d, period = parse_date_label(label.get_text(" ", strip=True), academic_year) if label else (None, None)
        desc = tile.select_one("p.lightText")
        description = desc.get_text("\n", strip=True) if desc else ""
        badges = {e["title"] for e in tile.select("[title]")}
        out.append(ParsedLesson(
            lms_lesson_id=lesson_id,
            position=int(pos.group(1)) if pos else len(out) + 1,
            title=_POSITION.sub("", raw_title).strip(),
            description="" if description == "وصف الدرس." else description,
            date=d,
            period=period,
            hidden=HIDDEN_BADGE in badges,
            awards_points=POINTS_BADGE in badges,
        ))
    return out


def parse_tiles(html: str) -> list[ParsedTile]:
    """جودة البطاقة من قائمة الدروس: الصورة، وعدد الأقسام، وشارة النتاجات."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tile in soup.select("#blockView > div.draggable[id]"):
        style = " ".join(e.get("style", "") for e in tile.select("[style]"))
        label = tile.select_one(".footer .label")
        count = re.search(r"\d+", label.get_text(" ", strip=True)) if label else None
        out.append(ParsedTile(
            lms_lesson_id=int(tile["id"]),
            image_default="/images/default-images/" in style or "url(" not in style,
            sections=int(count.group()) if count else 0,
            has_outcomes=tile.select_one(".footer i.graph") is not None,
        ))
    return out


def parse_sections(html: str) -> list[ParsedSection]:
    """أقسام الدرس من صفحته (تبويب الأقسام) بترتيبها وأنواعها."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for row in soup.select("#section_list > tr"):
        link, icon = row.select_one("a[href*='section_id=']"), row.select_one("i.icnColor")
        if not link:
            continue
        raw = next((c for c in icon.get("class", []) if c not in ("small", "icnColor")), "") if icon else ""
        out.append(ParsedSection(
            section_id=int(re.search(r"section_id=(\d+)", link["href"]).group(1)),
            title=link.get_text(" ", strip=True),
            kind=raw,
        ))
    return out


def parse_outcomes(html: str) -> list[tuple[str, str]]:
    """نتاجات التعلم المربوطة بالدرس (صفحة show_competencies): (الرمز، النص)."""
    out = []
    for a in BeautifulSoup(html, "lxml").select(".proficiencyItem a"):
        m = re.match(r"\s*([\d.]+?)\.?\s+(.*)", a.get_text(" ", strip=True), re.S)
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


def parse_available_outcomes(html: str) -> list[dict]:
    """نتاجات الصف المتاحة للربط (صفحة edit_competencies): معرّف المنصة ورمز النتاج ونصه."""
    out = []
    for cb in BeautifulSoup(html, "lxml").select("input[name='proficiencies[]']"):
        a = cb.find_next("a", href=re.compile(rf"proficiency_id={cb['value']}\b"))
        m = a and re.match(r"\s*([\d.]+?)\.?\s+(.*)", a.get_text(" ", strip=True), re.S)
        if m:
            out.append({"id": int(cb["value"]), "code": m.group(1), "text": m.group(2).strip()})
    return out


def parse_assessments(html: str) -> list[ParsedAssessment]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for row in soup.select("tr"):
        box = row.select_one("input[name='select[]']")
        cell = row.select_one("td.assignment")
        if not box or not cell:
            continue
        title = cell.select_one(":scope > a")
        lesson = cell.select_one("a[href*='lesson_id=']")
        out.append(ParsedAssessment(
            lms_assignment_id=int(box["value"]),
            title=title.get_text(strip=True) if title else "",
            lms_lesson_id=int(re.search(r"lesson_id=(\d+)", lesson["href"]).group(1)) if lesson else None,
            given=row.select_one("i.tick") is not None,
        ))
    return out


def parse_timetable(html: str) -> list[ParsedSlot]:
    soup = BeautifulSoup(html, "lxml")
    slots = []
    for row in soup.select("tr"):
        if not row.select_one("input[name=class_time]"):
            continue
        cells = [c.get_text(strip=True) for c in row.select("td")]
        day = next((WEEKDAYS[c] for c in cells if c in WEEKDAYS), None)
        period = next((int(m.group(1) or m.group(2))
                       for c in cells if (m := re.search(r"Period\s*(\d+)|الحصة\s*(\d+)", c))), None)
        if day is not None and period is not None:
            slots.append(ParsedSlot(day, period))
    return slots


def parse_default_visibility(html: str) -> bool | None:
    """تبويب «الرؤية»: True إن كان الدرس ظاهرًا افتراضيًا، None إن لم يوجد الخيار."""
    checked = BeautifulSoup(html, "lxml").select_one("input[name=default_visibility][checked]")
    return None if checked is None else checked["value"] == "Show"


def parse_points_actions(html: str) -> int:
    """تبويب «متطلبات الإنجاز»: عدد إجراءات منح النقاط عند إنجاز الدرس."""
    return len(BeautifulSoup(html, "lxml").select("table.rulesList tr i.star2"))


def parse_points_games(html: str) -> list[str]:
    """نموذج «منح النقاط»: أسماء الألعاب المتاحة في الصف."""
    return [o.get_text(strip=True) for o in
            BeautifulSoup(html, "lxml").select("select[name='rule_action[arg2_id]'] option") if o.get("value")]


_STUDENT_LESSON = re.compile(r"/student_lesson/show/\d+\?lesson_id=(\d+)")


def parse_student_lessons(html: str) -> tuple[set[int], set[int]]:
    """قائمة دروس الطالب: (بطاقات الدروس الظاهرة، دروس لوحة «اليوم»)."""
    soup = BeautifulSoup(html, "lxml")

    def ids(links):
        return {int(m.group(1)) for a in links if (m := _STUDENT_LESSON.search(a.get("href", "")))}

    today = soup.find("i", class_="اليوم")
    today_block = today.find_parent("div", class_="block") if today else None
    return (ids(soup.select("#blockView > a[href]")),
            ids(today_block.select("a[href]")) if today_block else set())


def is_login_url(url: str) -> bool:
    return any(s in url for s in ("/log_in", "not_logged_in", "log_in_required"))


def is_login_page(html: str) -> bool:
    return 'action="/log_in' in html or "id=\"login_form\"" in html


def parse_question_text(html: str) -> str:
    """نص السؤال من صفحة عرضه في بنك الأسئلة: أول div.materialStyle بعد عنوان النوع، بلا وسوم ولا فراغات زائدة."""
    node = BeautifulSoup(html, "html.parser").select_one("div.materialStyle")
    return re.sub(r"\s+", " ", node.get_text(" ")).strip() if node else ""


_FILE_HREF = re.compile(r"^(?:https?://[^/]+)?(/files/(\d+)/([^/?#]+?)\.(docx|pptx|pdf|doc|ppt|xlsx)(?:\?[^#]*)?)$", re.I)


def parse_file_links(html: str) -> list[FileLink]:
    """روابط الملفات في صفحة (ملاحظات المعلم، قسم عرض، مجلد مصادر) بترتيبها، بلا تكرار للملف نفسه.
    اسم العرض هو نص الرابط؛ إن خلا فالعنوان، ثم الاسم المرمّز في المسار."""
    out, seen = [], set()
    for a in BeautifulSoup(html, "lxml").select("a[href*='/files/']"):
        m = _FILE_HREF.match(a.get("href", "").strip())
        if not m:
            continue
        name = a.get_text(" ", strip=True) or a.get("title", "").strip() or m.group(3)
        link = FileLink(int(m.group(2)), m.group(1), name, m.group(3), m.group(4).lower())
        if link.key not in seen:
            seen.add(link.key)
            out.append(link)
    return out


