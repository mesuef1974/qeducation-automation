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
    Task("card", "بطاقة الدرس: الصورة والوصف", "content", 0, 2, 40),
    Task("sections", "أقسام الدرس ومحتواه", "content", 0, 2, 120),
    Task("paths", "المسارات العلاجية والإثرائية", "content", 0, 2, 45),
    Task("questions", "إعداد أسئلة التقييم", "assess", 0, 2, 90),
    Task("grading", "التصحيح ومتابعة الدرجات", "assess", 0, 2, 60),
    Task("follow", "متابعة دخول الطلاب وتأخرهم", "students", 0, 3, 30),
    Task("parents", "التواصل مع أولياء الأمور", "students", 0, 2, 30),
    Task("badges", "الشارات وإنجاز الصف", "students", 0, 2, 10),
)


@dataclass(frozen=True)
class Capability:
    title: str
    used: bool


CAPABILITIES = (
    Capability("الدروس وتواريخها", True),
    Capability("التقييمات والإسناد", True),
    Capability("الإظهار والإخفاء", True),
    Capability("لعبة النقاط", True),
    Capability("عرض الطالب", True),
    Capability("الجدول الدراسي", True),
    Capability("بطاقة الدرس وصورته", False),
    Capability("بنك الأسئلة", False),
    Capability("الشارات", False),
    Capability("إنجاز الصف", False),
    Capability("مسارات التعلم", False),
    Capability("أولياء الأمور", False),
    Capability("الرسائل والإعلانات", False),
    Capability("التقارير والتحليلات", False),
)

# شروط الامتثال (نجاح أو إخفاق)؛ تتغير بقرار لا ببيانات
COMPLIANCE = (
    ("بيانات الطلاب محلية فقط، والأسماء محجوبة فيما يُشارك (PDPPL)", True),
    ("المحتوى والرسائل والعمليات الخطرة لا تُطبَّق إلا باعتماد المعلم", True),
    ("المحتوى الموجود لا يُعدَّل ولا يُحذف؛ إضافة للناقص فقط", True),
    ("كل عملية على المنصة مسجلة في سجل التدقيق", True),
    ("لا كلمات مرور ولا ملفات جلسة في المستودع", True),
)
