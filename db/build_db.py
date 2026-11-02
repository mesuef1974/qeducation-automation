"""
بناء قاعدة بيانات الخطط الفصلية لمادة الرياضيات 2026-2027 - الفصل الأول.
المصدر: نموذج ES-ESM-P3-F1 (إدارة التوجيه التربوي - قسم الرياضيات).
التشغيل: python -I build_db.py  ← يعيد البناء من الصفر (idempotent).
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "math_plans_2026_2027.db"
XLSX_PATH = HERE / "math_plans_2026_2027.xlsx"

TERM_START = date(2026, 8, 30)  # الأحد - بداية الأسبوع الأول

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE source_documents (
    doc_id          INTEGER PRIMARY KEY,
    form_code       TEXT NOT NULL,
    issue_no        INTEGER NOT NULL,
    issue_date      TEXT NOT NULL,
    classification  TEXT NOT NULL,
    department      TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    page_count      INTEGER NOT NULL
);

CREATE TABLE plans (
    plan_id        INTEGER PRIMARY KEY,
    doc_id         INTEGER NOT NULL REFERENCES source_documents(doc_id),
    subject        TEXT NOT NULL,
    academic_year  TEXT NOT NULL,
    term_no        INTEGER NOT NULL,
    grade_level    INTEGER NOT NULL,
    tracks         TEXT,
    shift          TEXT NOT NULL,
    platform_class TEXT,
    UNIQUE (subject, academic_year, term_no, grade_level, tracks, shift)
);

CREATE TABLE units (
    unit_id   INTEGER PRIMARY KEY,
    plan_id   INTEGER NOT NULL REFERENCES plans(plan_id),
    unit_no   INTEGER NOT NULL,
    title     TEXT NOT NULL,
    domain    TEXT NOT NULL,
    UNIQUE (plan_id, unit_no)
);

CREATE TABLE weeks (
    week_id     INTEGER PRIMARY KEY,
    plan_id     INTEGER NOT NULL REFERENCES plans(plan_id),
    week_no     INTEGER NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    week_type   TEXT NOT NULL CHECK (week_type IN ('تدريس','إجازة')),
    note        TEXT,
    UNIQUE (plan_id, week_no)
);

CREATE TABLE lessons (
    lesson_id     INTEGER PRIMARY KEY,
    plan_id       INTEGER NOT NULL REFERENCES plans(plan_id),
    unit_id       INTEGER NOT NULL REFERENCES units(unit_id),
    lesson_code   TEXT NOT NULL,
    title         TEXT NOT NULL,
    in_schedule   INTEGER NOT NULL CHECK (in_schedule IN (0,1)),
    total_periods INTEGER NOT NULL DEFAULT 0,
    UNIQUE (plan_id, lesson_code)
);

CREATE TABLE schedule_entries (
    entry_id      INTEGER PRIMARY KEY,
    plan_id       INTEGER NOT NULL REFERENCES plans(plan_id),
    week_id       INTEGER NOT NULL REFERENCES weeks(week_id),
    seq           INTEGER NOT NULL,
    unit_id       INTEGER REFERENCES units(unit_id),
    lesson_id     INTEGER REFERENCES lessons(lesson_id),
    activity_type TEXT NOT NULL,
    title         TEXT NOT NULL,
    periods       INTEGER NOT NULL CHECK (periods > 0),
    UNIQUE (week_id, seq)
);

CREATE TABLE competencies (
    competency_id INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE
);

CREATE TABLE core_values (
    value_id INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE
);

-- كتلة = خلية مدموجة في الجدول الأصلي تجمع الكفايات والقيم والمكتسبات لمدى أسابيع
CREATE TABLE outcome_blocks (
    block_id   INTEGER PRIMARY KEY,
    plan_id    INTEGER NOT NULL REFERENCES plans(plan_id),
    unit_id    INTEGER NOT NULL REFERENCES units(unit_id),
    week_from  INTEGER NOT NULL,
    week_to    INTEGER NOT NULL,
    CHECK (week_from <= week_to)
);

CREATE TABLE block_competencies (
    block_id      INTEGER NOT NULL REFERENCES outcome_blocks(block_id),
    competency_id INTEGER NOT NULL REFERENCES competencies(competency_id),
    PRIMARY KEY (block_id, competency_id)
);

CREATE TABLE block_values (
    block_id INTEGER NOT NULL REFERENCES outcome_blocks(block_id),
    value_id INTEGER NOT NULL REFERENCES core_values(value_id),
    PRIMARY KEY (block_id, value_id)
);

CREATE TABLE learning_outcomes (
    outcome_id INTEGER PRIMARY KEY,
    block_id   INTEGER NOT NULL REFERENCES outcome_blocks(block_id),
    seq        INTEGER NOT NULL,
    text       TEXT NOT NULL,
    UNIQUE (block_id, seq)
);

CREATE TABLE calendar_events (
    event_id   INTEGER PRIMARY KEY,
    plan_id    INTEGER NOT NULL REFERENCES plans(plan_id),
    event_type TEXT NOT NULL,
    title      TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    note       TEXT
);

CREATE TABLE enrichment_items (
    item_id   INTEGER PRIMARY KEY,
    plan_id   INTEGER NOT NULL REFERENCES plans(plan_id),
    unit_id   INTEGER NOT NULL REFERENCES units(unit_id),
    lesson_id INTEGER NOT NULL REFERENCES lessons(lesson_id),
    detail    TEXT
);

CREATE TABLE guidelines (
    guideline_id INTEGER PRIMARY KEY,
    plan_id      INTEGER NOT NULL REFERENCES plans(plan_id),
    seq          INTEGER NOT NULL,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    UNIQUE (plan_id, seq)
);

CREATE TABLE teaching_methodology (
    step_id   INTEGER PRIMARY KEY,
    plan_id   INTEGER NOT NULL REFERENCES plans(plan_id),
    seq       INTEGER NOT NULL,
    component TEXT NOT NULL,
    procedure TEXT NOT NULL,
    UNIQUE (plan_id, seq)
);

CREATE INDEX ix_entries_plan_week ON schedule_entries(plan_id, week_id);
CREATE INDEX ix_weeks_dates ON weeks(start_date, end_date);

CREATE VIEW v_schedule AS
SELECT p.grade_level, w.week_no, w.start_date, w.end_date, e.seq,
       u.unit_no, u.title AS unit_title, e.activity_type,
       l.lesson_code, e.title, e.periods
FROM schedule_entries e
JOIN plans p  ON p.plan_id = e.plan_id
JOIN weeks w  ON w.week_id = e.week_id
LEFT JOIN units u   ON u.unit_id = e.unit_id
LEFT JOIN lessons l ON l.lesson_id = e.lesson_id
ORDER BY p.grade_level, w.week_no, e.seq;

CREATE VIEW v_week_totals AS
SELECT p.grade_level, w.week_no, w.start_date, w.end_date, w.week_type,
       COALESCE(SUM(e.periods), 0) AS periods
FROM weeks w
JOIN plans p ON p.plan_id = w.plan_id
LEFT JOIN schedule_entries e ON e.week_id = w.week_id
GROUP BY w.week_id
ORDER BY p.grade_level, w.week_no;

CREATE VIEW v_unit_totals AS
SELECT p.grade_level, u.unit_no, u.title, u.domain,
       COUNT(DISTINCT e.lesson_id) AS lessons, SUM(e.periods) AS periods,
       MIN(w.week_no) AS first_week, MAX(w.week_no) AS last_week
FROM units u
JOIN plans p ON p.plan_id = u.plan_id
JOIN schedule_entries e ON e.unit_id = u.unit_id
JOIN weeks w ON w.week_id = e.week_id
GROUP BY u.unit_id
ORDER BY p.grade_level, u.unit_no;

CREATE VIEW v_outcomes AS
SELECT p.grade_level, u.unit_no, b.week_from, b.week_to,
       (SELECT group_concat(c.name, '، ') FROM block_competencies bc
          JOIN competencies c ON c.competency_id = bc.competency_id
         WHERE bc.block_id = b.block_id) AS competencies,
       (SELECT group_concat(v.name, '، ') FROM block_values bv
          JOIN core_values v ON v.value_id = bv.value_id
         WHERE bv.block_id = b.block_id) AS core_values,
       o.seq, o.text
FROM learning_outcomes o
JOIN outcome_blocks b ON b.block_id = o.block_id
JOIN units u ON u.unit_id = b.unit_id
JOIN plans p ON p.plan_id = b.plan_id
ORDER BY p.grade_level, b.week_from, o.seq;
"""

# ---------------------------------------------------------------- البيانات

COMMON_EVENTS = [
    ("بداية الفصل", "بداية الفصل الدراسي الأول", "2026-08-30", "2026-08-30", None),
    ("اختبارات", "اختبارات منتصف الفصل الأول", "2026-10-13", "2026-10-22", "لصفوف النقل"),
    ("إجازة", "إجازة منتصف الفصل الدراسي الأول", "2026-10-25", "2026-10-29", None),
    ("اختبارات", "اختبارات نهاية الفصل الدراسي الأول", "2026-12-06", "2026-12-15", None),
    ("إجازة", "إجازة منتصف العام الأكاديمي 2027/2026", "2026-12-20", "2026-12-31", None),
]

GUIDE_DIGITAL = (
    "المصادر الرقمية / الفيديوهات التعليمية",
    "يتوفر لكل درس من الدروس مجموعة من ثلاثة فيديوهات على الأقل يغطي كل منها هدفًا أو أكثر من أهداف "
    "الدرس عبر تقديم المفهوم (بما يشمل المقدمة والتعريف ومثال واحد وأحيانًا مثالين من كتاب الطالب) أو عبر "
    "تطبيقات على المفاهيم. أيضًا يمكن استعمال البرمجيات الحاسوبية مثل Desmos و GeoGebra، أو تطبيقات الذكاء "
    "الاصطناعي والأدوات الرقمية في دعم تعلم الرياضيات وتنمية مهارات التفكير العليا.",
)
GUIDE_ENRICH = (
    "الدروس الإثرائية",
    "استثمار الدروس والأمثلة الإثرائية في دعم التعلم الذاتي وتنمية مهارات الطلبة الأكاديمية، من خلال "
    "الاستفادة من منصة قطر للتعليم في إسناد واجبات وأنشطة تحفيزية تُعزز مفاهيم ومهارات الدروس الإثرائية.",
)

PLANS = [
    {
        "grade": 12,
        "tracks": "العلمي والتكنولوجي",
        "platform_class": "الرياضيات 12/2",
        "file": "الخطة الفصلية لمادة الرياضيات 2026-2027م - الفصل الأول - المستوى 12 - المسارين العلمي والتكنولوجي (نهاري).pdf",
        "pages": 3,
        "units": [
            (1, "النهايات والاتصال", "الحساب والجبر وحساب التفاضل والتكامل"),
            (2, "التفاضل", "الحساب والجبر وحساب التفاضل والتكامل"),
            (3, "تطبيقات التفاضل", "الحساب والجبر وحساب التفاضل والتكامل"),
        ],
        # (أسبوع، وحدة، نوع النشاط، رمز الدرس، العنوان، الحصص)
        "schedule": [
            (1, 1, "تهيئة", None, "تهيئة بداية الفصل الدراسي الأول", 2),
            (1, 1, "درس", "1.1", "مفهوم النهاية", 4),
            (2, 1, "درس", "1.2", "حساب النهايات", 4),
            (2, 1, "درس", "1.3", "نهايات الدوال المثلثية", 2),
            (3, 1, "درس", "1.3", "نهايات الدوال المثلثية", 1),
            (3, 1, "درس", "1.4", "الاتصال", 4),
            (3, 1, "مراجعة واختبار وحدة", None, "مراجعة واختبار الوحدة الأولى", 1),
            (4, 2, "درس", "2.1", "معدل التغير", 4),
            (4, 2, "درس", "2.2", "تعريف المشتقة", 2),
            (5, 2, "درس", "2.2", "تعريف المشتقة", 1),
            (5, 2, "درس", "2.3", "قواعد الاشتقاق", 3),
            (5, 2, "درس", "2.4", "قاعدتا الضرب والقسمة في الاشتقاق", 2),
            (6, 2, "درس", "2.4", "قاعدتا الضرب والقسمة في الاشتقاق", 1),
            (6, 2, "درس", "2.5", "قاعدة السلسلة", 3),
            (6, 2, "درس", "2.6", "مشتقات الدوال الأسية واللوغاريتمية", 2),
            (7, 2, "درس", "2.6", "مشتقات الدوال الأسية واللوغاريتمية", 1),
            (7, 2, "درس", "2.7", "مشتقات الدوال المثلثية", 3),
            (8, 2, "درس", "2.7", "مشتقات الدوال المثلثية", 1),
            (8, 2, "درس", "2.8", "الاشتقاق الضمني", 3),
            (10, 2, "درس", "2.9", "المشتقات من الرتب العليا", 4),
            (10, 2, "مراجعة واختبار وحدة", None, "مراجعة واختبار الوحدة الثانية", 1),
            (10, 3, "درس", "3.1", "الدوال المتزايدة والمتناقصة", 1),
            (11, 3, "درس", "3.1", "الدوال المتزايدة والمتناقصة", 3),
            (11, 3, "درس", "3.2", "القيم القصوى للدوال", 3),
            (12, 3, "درس", "3.2", "القيم القصوى للدوال", 1),
            (12, 3, "درس", "3.3", "التقعر ونقاط الانعطاف", 4),
            (12, 3, "درس", "3.4", "رسم منحنيات الدوال", 1),
            (13, 3, "درس", "3.4", "رسم منحنيات الدوال", 2),
            (13, 3, "درس", "3.5", "تطبيقات القيم القصوى", 4),
            (14, 3, "مراجعة واختبار وحدة", None, "مراجعة واختبار الوحدة الثالثة", 1),
            (14, None, "مراجعة اختبار نهاية الفصل", None, "مراجعة اختبار نهاية الفصل الدراسي الأول", 5),
        ],
        # دروس واردة في الإرشادات فقط وليست في التوزيع الأسبوعي
        "extra_lessons": [(3, "3.6", "المعدلات المرتبطة")],
        "outcome_blocks": [
            (1, 1, 3, ["التواصل", "التقصي والبحث"], ["الاحترام والتعاطف"], [
                "استكشاف وشرح العلاقات الممكنة بين دالتين غير متصلتين عند نقطة محددة، وإعطاء تفسير لذلك بإظهار احترام آراء الآخرين.",
            ]),
            (2, 4, 6, ["حل المشكلات", "الإبداع والتفكير الناقد"], ["الإيجابية والمثابرة"], [
                "تطبيق الاستدلال الاستقرائي لإيجاد المشتقة من الرتبة النونية للدوال الجذرية والأسية والنسبية، والعمل بإيجابية ومثابرة للبحث في العلاقات والتوصل لنتائج واكتساب مهارات رياضية جديدة.",
            ]),
            (2, 7, 8, ["حل المشكلات"], ["الحقوق والمسؤولية والنزاهة"], [
                "استعمال الوسائط والبرمجيات بشكل فعال ومسؤول لاستكشاف خواص مشتقات الدوال.",
            ]),
            (2, 10, 10, ["الإبداع والتفكير الناقد"], ["الإيجابية والمثابرة", "المهارات الحياتية"], [
                "الإيجابية والمثابرة في إيجاد المشتقات من الرتب العليا لدوال متنوعة، والتعرف على التطبيقات الفيزيائية للمشتقة الأولى والثانية واستعمالها في فهم ودراسة الظواهر الطبيعية والمواقف الحياتية.",
            ]),
            (3, 10, 14, ["التقصي والبحث", "التواصل", "حل المشكلات"], ["الاحترام والتعاطف", "الإيجابية والمثابرة"], [
                "استكشاف المزيد من المعلومات التي توفرها المشتقات عن سلوك الدوال وأشكال تمثيلاتها البيانية. على سبيل المثال: تصف المشتقة الأولى معدل تزايد أو تناقص الدوال، بينما تصف المشتقة الثانية معدل تغير التزايد أو التناقص.",
                "توظيف العلوم والتكنولوجيا والمهارات الحياتية في إنجاز مشروع الوحدة، وإظهار النزاهة واحترام الحقوق والمسؤولية في عرض ومناقشة النتائج.",
                "التعاون مع الآخرين لاستكشاف مواقف حياتية يمكن نمذجتها بمسألة الحل الأمثل ووصف الخطوات التي يجب اتخاذها في عملية حل المسألة.",
            ]),
        ],
        "enrichment": [
            (2, "2.2", "تفسير عدم وجود المشتقة + مثال 6 إثرائي"),
            (2, "2.6", "مثال 5 إثرائي"),
            (2, "2.8", "مثال 4 + مثال 5 إثرائي"),
            (2, "2.9", "مثال 6 إثرائي"),
            (3, "3.5", "مثال 4 إثرائي"),
            (3, "3.6", None),
        ],
        "guidelines": [
            GUIDE_DIGITAL,
            GUIDE_ENRICH,
            ("دعم تعلم الطلبة (الصفي / عن بعد)",
             "مراجعة خبرات الطلبة السابقة وتهيئتهم للتعلم الجديد.\n"
             "الاستفادة من المصادر المساندة (دليل المعلم - الكتب التفاعلية - دليل التقويم) بما يخدم تعلم الطلبة.\n"
             "إسناد واجبات وتطبيقات مستمرة للطلبة ومن ضمنها الواجبات الإلكترونية."),
        ],
        "methodology": [],
    },
    {
        "grade": 10,
        "tracks": None,
        "platform_class": "الرياضيات 10/3",
        "file": "الخطة الفصلية لمادة الرياضيات - العام الأكاديمي 2026-2027م - الفصل الأول - المستوى 10 (نهاري).pdf",
        "pages": 4,
        "units": [
            (1, "الدوال التربيعية", "الحساب والجبر"),
            (2, "المعادلات والمتباينات التربيعية", "الحساب والجبر"),
            (3, "تشابه المثلثات", "الهندسة والقياسات وحساب المثلثات"),
        ],
        "schedule": [
            (1, 1, "تهيئة", None, "تهيئة بداية الفصل الدراسي الأول", 2),
            (1, 1, "درس", "1.1", "المميزات الأساسية للدالة التربيعية", 3),
            (2, 1, "درس", "1.2", "الدوال التربيعية في صيغة الرأس", 3),
            (2, 1, "درس", "1.3", "الدوال التربيعية في الصيغة القياسية", 2),
            (3, 1, "درس", "1.3", "الدوال التربيعية في الصيغة القياسية", 1),
            (3, 1, "مراجعة واختبار وحدة", None, "مراجعة واختبار الوحدة الأولى", 1),
            (3, 2, "درس", "2.1", "حل المعادلات التربيعية باستعمال التمثيلات البيانية والجداول", 3),
            (4, 2, "درس", "2.2", "حل المعادلات التربيعية بالتحليل إلى العوامل", 4),
            (4, 2, "درس", "2.3", "إعادة كتابة المقادير الجذرية", 1),
            (5, 2, "درس", "2.3", "إعادة كتابة المقادير الجذرية", 3),
            (5, 2, "درس", "2.5", "إكمال المربع", 2),
            (6, 2, "درس", "2.5", "إكمال المربع", 2),
            (6, 2, "درس", "2.6", "القانون العام لحل المعادلة التربيعية والمميز", 3),
            (7, None, "مراجعة اختبار منتصف الفصل", None, "مراجعة اختبار منتصف الفصل الأول", 2),
            (7, None, "اختبار منتصف الفصل", None, "اختبار منتصف الفصل الأول", 2),
            (8, None, "مشروع STEM", None, "مشروع STEM", 2),
            (8, None, "دعم وتثبيت", None, "دعم وتثبيت المهارات الرياضية", 2),
            (10, 2, "درس", "2.7", "حل المعادلات النسبية", 3),
            (10, 2, "درس", "2.8", "حل أنظمة المعادلات الخطية والتربيعية", 2),
            (11, 2, "درس", "2.8", "حل أنظمة المعادلات الخطية والتربيعية", 1),
            (11, 2, "درس", "2.9", "حل المتباينات التربيعية في متغير واحد", 3),
            (11, 2, "درس", "2.10", "معادلة الدائرة في المستوى الإحداثي", 1),
            (12, 2, "درس", "2.10", "معادلة الدائرة في المستوى الإحداثي", 2),
            (12, 2, "مراجعة واختبار وحدة", None, "مراجعة واختبار الوحدة الثانية", 1),
            (12, 3, "درس", "3.3", "إثبات تشابه المثلثات", 2),
            (13, 3, "درس", "3.3", "إثبات تشابه المثلثات", 1),
            (13, 3, "درس", "3.4", "التشابه في المثلثات القائمة", 3),
            (13, 3, "درس", "3.5", "التناسب في المثلثات", 1),
            (14, 3, "درس", "3.5", "التناسب في المثلثات", 2),
            (14, 3, "مراجعة واختبار وحدة", None, "مراجعة واختبار الوحدة الثالثة", 1),
            (14, None, "مراجعة اختبار نهاية الفصل", None, "مراجعة اختبار نهاية الفصل الدراسي الأول", 2),
        ],
        "extra_lessons": [
            (1, "1.4", "النمذجة باستعمال الدوال التربيعية"),
            (2, "2.4", "حل المعادلات التربيعية باستعمال الجذور التربيعية"),
            (3, "3.1", "التمدد"),
            (3, "3.2", "تحويلات التشابه"),
        ],
        "outcome_blocks": [
            (1, 1, 3, ["الإبداع والتفكير الناقد", "حل المشكلات"], ["الإيجابية والمثابرة", "البيئة والاستدامة"], [
                "استخدام أنماط تفكير مختلفة وبرمجيات رياضية لاستكشاف خواص الدالة التربيعية، وتوظيف تلك الخواص في حل مسائل وتطبيقات من واقع الحياة.",
            ]),
            (2, 3, 8, ["التقصي والبحث", "التعاون والمشاركة"],
             ["الاحترام والتعاطف", "المسؤولية والنزاهة الشخصية", "المهارات الحياتية", "الإيجابية والمثابرة"], [
                "استعمال التمثيلات البيانية للدوال التربيعية لإيجاد حلول تقريبية لمسائل من واقع الحياة اليومية. على سبيل المثال: نمذجة مسار كرة مقذوفة في الهواء.",
                "توظيف الاستقصاء للبحث في العلاقات وبناء حجج رياضية توضح العلاقة بين مقاطع المحور الأفقي وعدد حلول المعادلة التربيعية.",
                "اشتقاق القانون العام لحل المعادلة التربيعية، واستكشاف المعنى الهندسي للمميز لشرح علاقة قيمة المميز بعدد جذور المعادلة التربيعية.",
                "توظيف العلوم والتكنولوجيا بشكل إبداعي وأخلاقي ومسؤول للبحث عن سيناريوهات لمواقف من الحياة اليومية تتطلب تطبيقات للدالة التربيعية، ضمن مجموعات عمل صغيرة ومناقشة وعرض النتائج في صورة بحث مصغر أو نموذج لمجسم أو عرض تقديمي، ...",
            ]),
            (2, 10, 12, ["التواصل", "حل المشكلات"], ["الاحترام والتعاطف"], [
                "شرح خطوات حل معادلات تتضمن كسورًا جبرية وشرح الحاجة للتحقق من الحلول غير المقبولة.",
                "استكشاف ووصف مواقف حياتية يُمكن نمذجتها بزوج من المعادلات إحداهما خطية والأخرى تربيعية وحلها.",
                "شرح وتوضيح الفرق بين حل المعادلة التربيعية وحل المتباينة التربيعية باستعمال تمثيل الحلول على خط الأعداد.",
            ]),
            (3, 12, 14, ["الإبداع والتفكير الناقد", "التواصل"], ["الإيجابية والمثابرة"], [
                "استنتاج العلاقة بين الشكل الهندسي وصورته الناتجة من تحويل التمدد والتوصل إلى أن الشكل وصورته تحت تأثير التمدد متشابهان.",
                "استنتاج وشرح حالات التشابه في المثلثات والتمكن من استعمالها لتحديد المثلثات المتشابهة، واستعمال الرموز بدقة لوصف تحويلات التشابه.",
            ]),
        ],
        "enrichment": [
            (1, "1.4", None),
            (2, "2.4", None),
            (2, "2.5", "مثال 5"),
            (2, "2.7", "مثال 4 + مثال 5"),
            (2, "2.9", "مثال 4"),
            (2, "2.10", "مثال 4"),
            (3, "3.1", None),
            (3, "3.2", None),
            (3, "3.3", "إثبات النظريات 1-2، 2-2، مثال 1 + مثال 2"),
            (3, "3.4", "مثال 6"),
            (3, "3.5", "مثال 4 + مثال 5"),
        ],
        "guidelines": [
            ("منهجية تدريس الخطة الفصلية لتغطية الدروس",
             "موضحة تفصيلًا في جدول teaching_methodology."),
            GUIDE_DIGITAL,
            GUIDE_ENRICH,
            ("دعم تعلم الطلبة (الصفي / عن بعد)",
             "مراجعة خبرات الطلبة السابقة وتهيئتهم للتعلم الجديد.\n"
             "تطبيق أحد مشاريع STEM الواردة في مصدر التعلم خلال الفصل الدراسي، وتكوين مجموعات عمل من الطلبة ومتابعتهم.\n"
             "الاستفادة من المصادر المساندة (دليل المعلم - الكتب التفاعلية - دليل التقويم - دليل ممارسات الرياضيات - دليل مشاريع STEM، ... إلخ) بما يخدم تعلم الطلبة.\n"
             "إسناد واجبات وتطبيقات مستمرة للطلبة ومن ضمنها الواجبات الإلكترونية."),
        ],
        "methodology": [
            ("استكشف / نمذج وناقش / استكشف وبرر منطقيًا", "تدرس باستعمال كتاب الطالب"),
            ("الأمثلة الثلاثة الأولى", "تدرس باستعمال النسخة الرقمية لكل منها"),
            ("الأمثلة المتبقية", "تدرس في كتاب الطالب"),
            ("عزز فهمك", "لكل مثال يُشرح، حل تمرين واحد مرتبط به"),
            ("عبر عن فهمك + طبق فهمك", "لكل مثال يُشرح، حل جميع التمارين المرتبطة به"),
            ("تدرب", "لكل مثال يُشرح، حل تمرين واحد من مجموعة التمارين المرتبطة به"),
            ("طبق", "اختيار تمرين واحد من التمارين"),
            ("تدرب على اختبار", "حل جميع التمارين"),
            ("المهمة الأدائية", "تتم مناقشتها في الصف ويمكن إعطاؤها في صورة واجب منزلي"),
        ],
    },
]

# المجاميع الأسبوعية كما تظهر في الأصل - تُستخدم للتحقق
EXPECTED_WEEK_TOTALS = {
    12: {1: 6, 2: 6, 3: 6, 4: 6, 5: 6, 6: 6, 7: 4, 8: 4, 9: 0, 10: 6, 11: 6, 12: 6, 13: 6, 14: 6},
    10: {1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 4, 8: 4, 9: 0, 10: 5, 11: 5, 12: 5, 13: 5, 14: 5},
}


# ---------------------------------------------------------------- البناء

def week_dates(week_no: int) -> tuple[str, str]:
    start = TERM_START + timedelta(weeks=week_no - 1)
    return start.isoformat(), (start + timedelta(days=4)).isoformat()


def lookup_id(cur, table, id_col, name):
    cur.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES (?)", (name,))
    return cur.execute(f"SELECT {id_col} FROM {table} WHERE name = ?", (name,)).fetchone()[0]


def load_plan(cur, p):
    cur.execute(
        "INSERT INTO source_documents(form_code, issue_no, issue_date, classification, department, file_name, page_count)"
        " VALUES ('ES-ESM-P3-F1', 1, '2024-05-30', 'داخلي', 'إدارة التوجيه التربوي - قسم الرياضيات', ?, ?)",
        (p["file"], p["pages"]),
    )
    cur.execute(
        "INSERT INTO plans(doc_id, subject, academic_year, term_no, grade_level, tracks, shift, platform_class)"
        " VALUES (?, 'الرياضيات', '2026-2027', 1, ?, ?, 'نهاري', ?)",
        (cur.lastrowid, p["grade"], p["tracks"], p["platform_class"]),
    )
    plan_id = cur.lastrowid

    units = {}
    for no, title, domain in p["units"]:
        cur.execute("INSERT INTO units(plan_id, unit_no, title, domain) VALUES (?,?,?,?)", (plan_id, no, title, domain))
        units[no] = cur.lastrowid

    weeks = {}
    for no in range(1, 15):
        s, e = week_dates(no)
        is_break = no == 9
        cur.execute(
            "INSERT INTO weeks(plan_id, week_no, start_date, end_date, week_type, note) VALUES (?,?,?,?,?,?)",
            (plan_id, no, s, e, "إجازة" if is_break else "تدريس",
             "إجازة منتصف الفصل - غير مرقّم في الخطة الأصلية" if is_break else None),
        )
        weeks[no] = cur.lastrowid

    lessons = {}
    for _, unit_no, kind, code, title, _ in p["schedule"]:
        if code and code not in lessons:
            cur.execute(
                "INSERT INTO lessons(plan_id, unit_id, lesson_code, title, in_schedule) VALUES (?,?,?,?,1)",
                (plan_id, units[unit_no], code, title),
            )
            lessons[code] = cur.lastrowid
    for unit_no, code, title in p["extra_lessons"]:
        cur.execute(
            "INSERT INTO lessons(plan_id, unit_id, lesson_code, title, in_schedule) VALUES (?,?,?,?,0)",
            (plan_id, units[unit_no], code, title),
        )
        lessons[code] = cur.lastrowid

    seq_by_week = {}
    for week_no, unit_no, kind, code, title, periods in p["schedule"]:
        seq_by_week[week_no] = seq_by_week.get(week_no, 0) + 1
        cur.execute(
            "INSERT INTO schedule_entries(plan_id, week_id, seq, unit_id, lesson_id, activity_type, title, periods)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (plan_id, weeks[week_no], seq_by_week[week_no], units.get(unit_no),
             lessons.get(code), kind, title, periods),
        )
    cur.execute(
        "UPDATE lessons SET total_periods = COALESCE((SELECT SUM(periods) FROM schedule_entries e"
        " WHERE e.lesson_id = lessons.lesson_id), 0) WHERE plan_id = ?",
        (plan_id,),
    )

    for unit_no, w_from, w_to, comps, vals, outcomes in p["outcome_blocks"]:
        cur.execute(
            "INSERT INTO outcome_blocks(plan_id, unit_id, week_from, week_to) VALUES (?,?,?,?)",
            (plan_id, units[unit_no], w_from, w_to),
        )
        block_id = cur.lastrowid
        for c in comps:
            cur.execute("INSERT INTO block_competencies VALUES (?,?)",
                        (block_id, lookup_id(cur, "competencies", "competency_id", c)))
        for v in vals:
            cur.execute("INSERT INTO block_values VALUES (?,?)",
                        (block_id, lookup_id(cur, "core_values", "value_id", v)))
        for i, text in enumerate(outcomes, 1):
            cur.execute("INSERT INTO learning_outcomes(block_id, seq, text) VALUES (?,?,?)", (block_id, i, text))

    cur.executemany(
        "INSERT INTO calendar_events(plan_id, event_type, title, start_date, end_date, note) VALUES (?,?,?,?,?,?)",
        [(plan_id, *ev) for ev in COMMON_EVENTS],
    )
    cur.executemany(
        "INSERT INTO enrichment_items(plan_id, unit_id, lesson_id, detail) VALUES (?,?,?,?)",
        [(plan_id, units[u], lessons[c], d) for u, c, d in p["enrichment"]],
    )
    cur.executemany(
        "INSERT INTO guidelines(plan_id, seq, title, body) VALUES (?,?,?,?)",
        [(plan_id, i, t, b) for i, (t, b) in enumerate(p["guidelines"], 1)],
    )
    cur.executemany(
        "INSERT INTO teaching_methodology(plan_id, seq, component, procedure) VALUES (?,?,?,?)",
        [(plan_id, i, c, pr) for i, (c, pr) in enumerate(p["methodology"], 1)],
    )


def verify(cur):
    for grade, expected in EXPECTED_WEEK_TOTALS.items():
        actual = dict(cur.execute(
            "SELECT week_no, periods FROM v_week_totals WHERE grade_level = ?", (grade,)).fetchall())
        assert actual == expected, f"الصف {grade}: مجاميع الأسابيع لا تطابق الأصل\n{actual}"
    for (d,) in cur.execute("SELECT start_date FROM weeks WHERE week_no = 1"):
        assert date.fromisoformat(d).weekday() == 6, "الأسبوع يجب أن يبدأ الأحد"
    bad = cur.execute("SELECT COUNT(*) FROM lessons WHERE in_schedule = 1 AND total_periods = 0").fetchone()[0]
    assert bad == 0
    assert cur.execute("PRAGMA foreign_key_check").fetchall() == []


def export_xlsx(conn):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    sheets = [
        ("التوزيع الأسبوعي", "SELECT grade_level AS 'الصف', week_no AS 'الأسبوع', start_date AS 'من', end_date AS 'إلى',"
         " seq AS 'م', unit_no AS 'الوحدة', unit_title AS 'اسم الوحدة', activity_type AS 'النوع',"
         " lesson_code AS 'الدرس', title AS 'العنوان', periods AS 'الحصص' FROM v_schedule"),
        ("مجاميع الأسابيع", "SELECT grade_level AS 'الصف', week_no AS 'الأسبوع', start_date AS 'من', end_date AS 'إلى',"
         " week_type AS 'النوع', periods AS 'الحصص' FROM v_week_totals"),
        ("الدروس", "SELECT p.grade_level AS 'الصف', u.unit_no AS 'الوحدة', l.lesson_code AS 'الدرس', l.title AS 'العنوان',"
         " CASE l.in_schedule WHEN 1 THEN 'نعم' ELSE 'إثرائي فقط' END AS 'في التوزيع', l.total_periods AS 'الحصص'"
         " FROM lessons l JOIN plans p USING(plan_id) JOIN units u USING(unit_id)"
         " ORDER BY p.grade_level, CAST(l.lesson_code AS REAL), l.lesson_code"),
        ("الوحدات", "SELECT grade_level AS 'الصف', unit_no AS 'الوحدة', title AS 'الاسم', domain AS 'المجال',"
         " lessons AS 'عدد الدروس', periods AS 'الحصص', first_week AS 'من أسبوع', last_week AS 'إلى أسبوع' FROM v_unit_totals"),
        ("المكتسبات", "SELECT grade_level AS 'الصف', unit_no AS 'الوحدة', week_from AS 'من أسبوع', week_to AS 'إلى أسبوع',"
         " competencies AS 'الكفايات ومهارات القرن 21', core_values AS 'القيم والقضايا المشتركة', seq AS 'م',"
         " text AS 'مكتسب التعلم' FROM v_outcomes"),
        ("الإثرائي", "SELECT p.grade_level AS 'الصف', u.unit_no AS 'الوحدة', l.lesson_code AS 'الدرس', l.title AS 'العنوان',"
         " COALESCE(e.detail, 'الدرس كاملًا') AS 'المحتوى الإثرائي' FROM enrichment_items e JOIN plans p USING(plan_id)"
         " JOIN units u ON u.unit_id = e.unit_id JOIN lessons l ON l.lesson_id = e.lesson_id ORDER BY p.grade_level, e.item_id"),
        ("التقويم", "SELECT DISTINCT event_type AS 'النوع', title AS 'الحدث', start_date AS 'من', end_date AS 'إلى',"
         " COALESCE(note, '') AS 'ملاحظة' FROM calendar_events ORDER BY start_date"),
        ("منهجية التدريس", "SELECT seq AS 'م', component AS 'الجزئية', procedure AS 'الإجراء' FROM teaching_methodology ORDER BY seq"),
        ("الإرشادات", "SELECT p.grade_level AS 'الصف', g.seq AS 'م', g.title AS 'العنوان', g.body AS 'النص'"
         " FROM guidelines g JOIN plans p USING(plan_id) ORDER BY p.grade_level, g.seq"),
    ]
    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="7B1E2B")  # عنابي قطر كما في النموذج
    for i, (name, sql) in enumerate(sheets, 1):
        cur = conn.execute(sql)
        ws = wb.create_sheet(name)
        ws.sheet_view.rightToLeft = True
        ws.append([d[0] for d in cur.description])
        for row in cur:
            ws.append(list(row))
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = header_fill
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(8, width + 2), 70)
            for c in col:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
        tab = Table(displayName=f"T{i}", ref=ws.dimensions)
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(tab)
    wb.save(XLSX_PATH)


def main():
    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        cur = conn.cursor()
        for p in PLANS:
            load_plan(cur, p)
        verify(cur)
        conn.commit()
        export_xlsx(conn)
    finally:
        conn.close()
    print(f"OK: {DB_PATH.name}, {XLSX_PATH.name}")


if __name__ == "__main__":
    main()
