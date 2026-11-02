"""
قراءة ملف الخطة (Excel) وكتابته. تعريف الأوراق والأعمدة في SHEETS مصدر واحد للقارئ والكاتب والقالب.
رموز الدروس نص دائمًا: "2.10" لو خُزّنت رقمًا لصارت 2.1، لذلك يُرفض الرقم ويُنسَّق العمود نصًا.
"""
from datetime import date, datetime
from pathlib import Path

from curriculum.domain.plan_spec import (
    BREAK,
    TEACHING,
    EntrySpec,
    EnrichmentSpec,
    EventSpec,
    ExtraLessonSpec,
    PlanFileError,
    PlanSpec,
    SourceInfo,
    UnitSpec,
    WeekSpec,
    group_blocks,
)

META = "بيانات الخطة"
# (العنوان، الحقل، النوع، مطلوب)
META_FIELDS = [
    ("المادة", "subject", str, True),
    ("العام الأكاديمي", "academic_year", str, True),
    ("الفصل", "term_no", int, True),
    ("المستوى", "grade_level", int, True),
    ("المسارات", "tracks", str, False),
    ("الفترة", "shift", str, True),
    ("الصف على المنصة", "platform_class", str, False),
    ("ملف المصدر", "file_name", str, True),
    ("عدد الصفحات", "page_count", int, True),
    ("رمز النموذج", "form_code", str, False),
    ("رقم الإصدار", "issue_no", int, False),
    ("تاريخ الإصدار", "issue_date", date, False),
    ("التصنيف", "classification", str, False),
    ("الجهة", "department", str, False),
]
SOURCE_FIELDS = {"file_name", "page_count", "form_code", "issue_no", "issue_date", "classification", "department"}

CODE = "code"  # نص إلزامي التنسيق
LIST = "list"  # قائمة مفصولة بـ «،»
# الورقة ← [(العنوان، النوع، مطلوب)]
SHEETS = {
    "الأسابيع": [("الأسبوع", int, True), ("من", date, True), ("إلى", date, True), ("النوع", str, True),
                 ("ملاحظة", str, False), ("الحصص المتوقعة", int, False)],
    "الوحدات": [("الوحدة", int, True), ("الاسم", str, True), ("المجال", str, False)],
    "التوزيع": [("الأسبوع", int, True), ("الوحدة", int, False), ("النوع", str, True), ("رمز الدرس", CODE, False),
                ("العنوان", str, True), ("الحصص", int, True)],
    "دروس خارج التوزيع": [("الوحدة", int, True), ("رمز الدرس", CODE, True), ("العنوان", str, True)],
    "المكتسبات": [("الكتلة", int, True), ("الوحدة", int, True), ("من أسبوع", int, True), ("إلى أسبوع", int, True),
                  ("الكفايات ومهارات القرن 21", LIST, False), ("القيم والقضايا المشتركة", LIST, False),
                  ("مكتسب التعلم", str, True)],
    "الإثراء": [("رمز الدرس", CODE, True), ("المحتوى الإثرائي", str, False)],
    "التقويم": [("النوع", str, True), ("الحدث", str, True), ("من", date, True), ("إلى", date, True),
                ("ملاحظة", str, False)],
    "الإرشادات": [("العنوان", str, True), ("النص", str, True)],
    "المنهجية": [("الجزئية", str, True), ("الإجراء", str, True)],
}
LIST_SEPARATORS = ("،", ",", "\n")
ACTIVITY_TYPES = ("درس", "تهيئة", "مراجعة واختبار وحدة", "مراجعة اختبار منتصف الفصل", "اختبار منتصف الفصل",
                  "مشروع STEM", "دعم وتثبيت", "مراجعة اختبار نهاية الفصل")
INSTRUCTIONS = [
    "ملف خطة فصلية واحدة لمادة ومستوى وفصل. املأ الأوراق ثم: python backend/manage.py plan_file check <الملف>",
    "بعد سلامة الفحص: python backend/manage.py import_plans <الملف أو المجلد>  (الاستيراد تراكمي لا يمس الخطط الأخرى)",
    "هوية الخطة = المادة + العام + الفصل + المستوى + المسارات + الفترة؛ إعادة استيراد الملف نفسه تحدّث الخطة ولا تكررها.",
    "الأسابيع: تبدأ الأحد. النوع «تدريس» أو «إجازة». «الحصص المتوقعة» مجموع الأسبوع في الأصل ويُتحقق منه.",
    "التوزيع: سطر لكل بند بترتيبه داخل الأسبوع. البند من نوع «درس» يحتاج رمز درس ووحدة؛ والأنواع الأخرى رمزها فارغ.",
    "أنواع البنود المعتادة: " + "، ".join(ACTIVITY_TYPES) + ".",
    "رموز الدروس نص (مثل 2.10)؛ أعمدتها منسّقة نصًا فلا تغيّر تنسيقها.",
    "المكتسبات: سطر لكل مكتسب، والأسطر ذات رقم الكتلة نفسه تشترك في الوحدة والأسابيع والكفايات والقيم (من أول سطر).",
    "الكفايات والقيم تُفصل بـ «،».",
]


# ---------------------------------------------------------------- قراءة

def _cell(value, kind, where: str, errs: list[str]):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if kind is int:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError
            return int(value)
        if kind is date:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return date.fromisoformat(str(value).strip()[:10])
        if kind == CODE:
            if not isinstance(value, str):
                errs.append(f"{where}: رمز الدرس يجب أن يكون نصًا (نسّق الخلية نصًا واكتب {value} من جديد)")
                return str(value)
            return value.strip()
        if kind == LIST:
            text = str(value)
            for sep in LIST_SEPARATORS[1:]:
                text = text.replace(sep, LIST_SEPARATORS[0])
            return tuple(x.strip() for x in text.split(LIST_SEPARATORS[0]) if x.strip())
        return str(value).strip()
    except (TypeError, ValueError):
        errs.append(f"{where}: قيمة غير صالحة {value!r}")
        return None


def _rows(wb, sheet: str, errs: list[str]) -> list[tuple]:
    cols = SHEETS[sheet]
    if sheet not in wb.sheetnames:
        errs.append(f"الورقة «{sheet}» غير موجودة")
        return []
    ws = wb[sheet]
    header = [str(c).strip() if c else "" for c in next(ws.iter_rows(max_row=1, values_only=True), ())]
    idx = {}
    for title, _, _ in cols:
        if title not in header:
            errs.append(f"«{sheet}»: العمود «{title}» غير موجود")
            return []
        idx[title] = header.index(title)
    out = []
    for r, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not any(v not in (None, "") for v in row):
            continue
        vals = []
        for title, kind, required in cols:
            raw = row[idx[title]] if idx[title] < len(row) else None
            v = _cell(raw, kind, f"«{sheet}» السطر {r}، {title}", errs)
            if v is None and required:
                errs.append(f"«{sheet}» السطر {r}: «{title}» مطلوب")
            vals.append(v if v is not None else ({str: "", LIST: ()}.get(kind)))
        out.append(tuple(vals))
    return out


def read_plan(path: Path) -> PlanSpec:
    """يقرأ ملف الخطة ويتحقق منه؛ يرفع PlanFileError بكل الأخطاء دفعة واحدة."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    errs: list[str] = []
    try:
        meta = {}
        if META not in wb.sheetnames:
            errs.append(f"الورقة «{META}» غير موجودة")
        else:
            raw = {str(k).strip(): v for k, v, *_ in wb[META].iter_rows(min_row=2, values_only=True) if k}
            for title, attr, kind, required in META_FIELDS:
                v = _cell(raw.get(title), kind, f"«{META}»، {title}", errs)
                if v is None and required:
                    errs.append(f"«{META}»: «{title}» مطلوب")
                if v is not None:
                    meta[attr] = v
        data = {s: _rows(wb, s, errs) for s in SHEETS}
    finally:
        wb.close()
    if errs:
        raise PlanFileError(path.name, errs)

    source = SourceInfo(**{k: v for k, v in meta.items() if k in SOURCE_FIELDS})
    spec = PlanSpec(
        **{k: v for k, v in meta.items() if k not in SOURCE_FIELDS}, source=source,
        weeks=tuple(WeekSpec(*r) for r in data["الأسابيع"]),
        units=tuple(UnitSpec(*r) for r in data["الوحدات"]),
        entries=tuple(EntrySpec(w, u, t, c or None, ti, p) for w, u, t, c, ti, p in data["التوزيع"]),
        extra_lessons=tuple(ExtraLessonSpec(*r) for r in data["دروس خارج التوزيع"]),
        outcome_blocks=group_blocks(data["المكتسبات"]),
        enrichment=tuple(EnrichmentSpec(*r) for r in data["الإثراء"]),
        events=tuple(EventSpec(*r) for r in data["التقويم"]),
        guidelines=tuple(data["الإرشادات"]),
        methodology=tuple(data["المنهجية"]),
    )
    problems = spec.validate()
    if problems:
        raise PlanFileError(path.name, problems)
    return spec


def plan_files(path: Path) -> list[Path]:
    """ملف واحد أو كل ملفات الخطط في مجلد (وما تحته)، مع تجاهل ملفات Excel المؤقتة."""
    path = Path(path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"plan file or folder not found: {path}")
    return sorted(p for p in path.rglob("*.xlsx") if not p.name.startswith("~$"))


# ---------------------------------------------------------------- كتابة

def _rows_of(spec: PlanSpec) -> dict[str, list[tuple]]:
    sep = f"{LIST_SEPARATORS[0]} "
    blocks = [(i, b.unit_no, b.week_from, b.week_to, sep.join(b.competencies), sep.join(b.values), t)
              for i, b in enumerate(spec.outcome_blocks, 1) for t in b.outcomes]
    return {
        "الأسابيع": [(w.week_no, w.start_date, w.end_date, w.week_type, w.note, w.expected_periods) for w in spec.weeks],
        "الوحدات": [(u.unit_no, u.title, u.domain) for u in spec.units],
        "التوزيع": [(e.week_no, e.unit_no, e.activity_type, e.lesson_code, e.title, e.periods) for e in spec.entries],
        "دروس خارج التوزيع": [(x.unit_no, x.code, x.title) for x in spec.extra_lessons],
        "المكتسبات": blocks,
        "الإثراء": [(x.lesson_code, x.detail) for x in spec.enrichment],
        "التقويم": [(e.event_type, e.title, e.start_date, e.end_date, e.note) for e in spec.events],
        "الإرشادات": list(spec.guidelines),
        "المنهجية": list(spec.methodology),
    }


def write_plan(spec: PlanSpec | None, path: Path) -> Path:
    """يكتب ملف الخطة؛ spec=None يكتب قالبًا فارغًا."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="7B1E2B")  # عنابي
    wrap = Alignment(wrap_text=True, vertical="top")

    def style(ws, widths):
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "A2"
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for i, w in enumerate(widths):
            ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = w

    wb = Workbook()
    ws = wb.active
    ws.title = "تعليمات"
    ws.sheet_view.rightToLeft = True
    ws.append(["تعليمات ملف الخطة الفصلية"])
    ws["A1"].font = Font(bold=True, size=14)
    for line in INSTRUCTIONS:
        ws.append([line])
    ws.column_dimensions["A"].width = 120

    ws = wb.create_sheet(META)
    ws.append(["الحقل", "القيمة"])
    values = {} if spec is None else {**vars(spec), **vars(spec.source)}
    for title, attr, _, _ in META_FIELDS:
        ws.append([title, values.get(attr)])
    for row in ws.iter_rows(min_row=2):
        row[1].alignment = wrap
        if isinstance(row[1].value, date):
            row[1].number_format = "yyyy-mm-dd"
    style(ws, [22, 70])

    rows = _rows_of(spec) if spec else {s: [] for s in SHEETS}
    for sheet, cols in SHEETS.items():
        ws = wb.create_sheet(sheet)
        ws.append([title for title, _, _ in cols])
        for r in rows[sheet]:
            ws.append(list(r))
        widths = [10 if kind in (int, CODE) else 12 if kind is date else 60 if title in ("النص", "مكتسب التعلم")
                  else 34 for title, kind, _ in cols]
        style(ws, widths)
        for j, (title, kind, _) in enumerate(cols, 1):
            letter = ws.cell(1, j).column_letter
            if kind == CODE:  # نص حتى للأسطر الفارغة القادمة
                for i in range(2, max(ws.max_row, 300) + 1):
                    ws.cell(i, j).number_format = "@"
            elif kind is date:
                for i in range(2, ws.max_row + 1):
                    ws.cell(i, j).number_format = "yyyy-mm-dd"
            elif kind in (str, LIST):
                for i in range(2, ws.max_row + 1):
                    ws.cell(i, j).alignment = wrap
            if sheet == "الأسابيع" and title == "النوع":
                dv = DataValidation(type="list", formula1=f'"{TEACHING},{BREAK}"', allow_blank=False)
                ws.add_data_validation(dv)
                dv.add(f"{letter}2:{letter}300")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
