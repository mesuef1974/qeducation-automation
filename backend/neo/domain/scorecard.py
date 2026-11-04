"""
مخزون بطاقة الأداء: المهام المتكررة للمعلم وقدرات المنصة، ومستوى نضج كل منها.
ما لا يُقاس من قاعدة البيانات يُعرَّف هنا ويُحدَّث يدويًا عند تغيّره (مع كل مرحلة تُنجز).
"""
from dataclasses import dataclass

# مستوى النضج ← اسمه، وما يبقى من وقت المعلم في المهمة
LEVELS = {
    0: ("يدوي", 1.0),
    1: ("قراءة وعرض", 0.75),
    2: ("اقتراح ثم اعتماد ثم تطبيق", 0.3),
    3: ("تطبيق وتحقق ذاتي", 0.1),
    4: ("مجدول ويراقب نفسه", 0.05),
}


@dataclass(frozen=True)
class Task:
    key: str
    title: str
    area: str      # admin | content | assess | students
    level: int
    target: int
    minutes: int   # دقائق أسبوعيًا للصفين يدويًا (تقدير أولي، يُصحَّح بقياس المعلم)


TASKS = (
    Task("dates", "تأريخ الدروس من الخطة", "admin", 2, 4, 30),
    Task("assign", "إسناد التقييمات ومواعيدها", "admin", 2, 4, 25),
    Task("publish", "إظهار الدروس ومنح النقاط", "admin", 2, 4, 15),
    Task("verify", "التحقق من منظور الطالب", "admin", 1, 4, 10),
    Task("fetch", "متابعة حالة الدروس في المنصة", "admin", 1, 4, 5),
    Task("weekly", "التقرير الأسبوعي", "admin", 0, 4, 20),
    # منذ 2026-11-04: الحزمة تُبنى وتُعدَّل وتُتحقق ذاتيًا (Word وفحص الأعوام)؛ الجدولة بانتظار قرار المعلم
    Task("prep", "حزمة التحضير الأسبوعية والرسالة", "admin", 3, 4, 90),
    Task("card", "بطاقة الدرس: الصورة والوصف", "content", 2, 2, 40),
    Task("sections", "أقسام الدرس ومحتواه", "content", 2, 2, 120),
    Task("paths", "المسارات العلاجية والإثرائية", "content", 0, 2, 45),
    Task("questions", "إعداد أسئلة التقييم", "assess", 2, 2, 90),
    Task("grading", "التصحيح ومتابعة الدرجات", "assess", 0, 2, 60),
    Task("follow", "متابعة دخول الطلاب وتأخرهم", "students", 0, 3, 30),
    Task("parents", "التواصل مع أولياء الأمور", "students", 0, 2, 30),
    Task("badges", "الشارات وإنجاز الصف", "students", 0, 2, 10),
)


@dataclass(frozen=True)
class Capability:
    title: str
    group: str        # tab = تبويب في الصف | inner = قدرة داخل تبويب
    enabled: bool     # مفعّلة في إعدادات الصف (الإعدادات ← الخصائص، لقطة 2 نوفمبر 2026)
    used: bool        # مستعملة مع الطلاب هذا الفصل، بإفادة المعلم في 2 نوفمبر 2026
    automated: bool = False  # تقرؤها أو تكتبها الأتمتة


# التبويبات الـ 26 كما تعرضها المنصة، ثم 5 قدرات داخل التبويبات
CAPABILITIES = (
    Capability("الصفحة الرئيسية", "tab", True, True),
    Capability("الدروس", "tab", True, True, automated=True),
    Capability("الأخبار", "tab", True, True),
    Capability("التقويم", "tab", True, True),
    Capability("المجموعات", "tab", True, True),
    Capability("مرحبا", "tab", True, True),
    Capability("التقييمات", "tab", True, True, automated=True),
    Capability("دفتر الدرجات", "tab", True, True),
    Capability("الإتقان", "tab", True, False),
    Capability("المصادر", "tab", True, True),
    Capability("الطلاب", "tab", True, True),
    Capability("أولياء الأمور", "tab", True, False),
    Capability("المعلمون", "tab", True, True),
    Capability("المعلمون المساعدون", "tab", False, False),
    Capability("تلعيب التعلم", "tab", True, True, automated=True),
    Capability("مخطط المقاعد", "tab", False, False),
    Capability("الحضور والغياب", "tab", True, False),
    Capability("المنتديات", "tab", True, False),
    Capability("الدردشة", "tab", True, False),
    Capability("Wiki", "tab", False, False),
    Capability("المدونات", "tab", True, False),
    Capability("المنهج", "tab", False, False),
    Capability("آراء الزملاء", "tab", False, False),
    Capability("التشغيل الآلي", "tab", True, True),
    Capability("نشاط المستخدمين", "tab", False, False),
    Capability("ملف الإنجاز", "tab", True, True),
    Capability("بطاقة الدرس وصورته", "inner", True, False),
    Capability("بنك الأسئلة", "inner", True, False),
    Capability("الشارات", "inner", True, False),
    Capability("إنجاز الصف", "inner", True, False),
    Capability("مسارات التعلم", "inner", True, False),
)

# شروط الامتثال (نجاح أو إخفاق)؛ تتغير بقرار لا ببيانات
COMPLIANCE = (
    ("بيانات الطلاب محلية فقط، والأسماء محجوبة فيما يُشارك (PDPPL)", True),
    ("المحتوى والرسائل والعمليات الخطرة لا تُطبَّق إلا باعتماد المعلم", True),
    ("المحتوى الموجود لا يُعدَّل ولا يُحذف؛ إضافة للناقص فقط", True),
    ("كل عملية على المنصة مسجلة في سجل التدقيق", True),
    ("لا كلمات مرور ولا ملفات جلسة في المستودع", True),
)
