"""
جودة الدرس: ما يجعل الطالب يفتح الدرس ويتعلم منه. قواعد نقية تُطبَّق على ما تقرؤه الأتمتة من المنصة،
ولا تكتب شيئًا؛ الإضافة لاحقًا باعتماد المعلم وللناقص فقط.
"""
from dataclasses import dataclass

# أيقونة القسم في المنصة ← نوعه
SECTION_KINDS = {
    "powerpoint": "عرض", "package": "تفاعلي", "movieStrip": "فيديو", "link_go": "رابط", "quiz": "تقييم",
    "page": "صفحة", "pageText": "صفحة", "pdf": "ملف", "assignment": "واجب", "discussion": "نقاش",
}
ASSESSMENT_KINDS = {SECTION_KINDS["quiz"], SECTION_KINDS["assignment"]}  # بالتسمية بعد التحويل
MIN_SECTIONS = 3  # تهيئة، وشرح، وتقييم على الأقل
MIN_DESCRIPTION = 120  # معيار الخطوة ٢: الوصف 120 حرفًا على الأقل

ISSUES = {
    "generic_image": "صورة عامة",
    "no_description": "بلا وصف",
    "short_description": f"وصف أقصر من {MIN_DESCRIPTION} حرفًا",
    "few_sections": f"أقل من {MIN_SECTIONS} أقسام",
    "no_assessment": "بلا تقييم",
    "no_outcomes": "بلا نتاج",
    "no_tags": "بلا كلمات دلالية",
}


@dataclass(frozen=True)
class LessonQuality:
    image_default: bool
    description: str
    section_kinds: tuple[str, ...]  # أنواع الأقسام بترتيبها (تسميات SECTION_KINDS)
    has_outcomes: bool
    has_tags: bool = True

    @property
    def has_assessment(self) -> bool:
        return any(k in ASSESSMENT_KINDS for k in self.section_kinds)

    def issues(self) -> list[str]:
        found = []
        if self.image_default:
            found.append("generic_image")
        if not self.description.strip():
            found.append("no_description")
        elif len(self.description.strip()) < MIN_DESCRIPTION:
            found.append("short_description")
        if len(self.section_kinds) < MIN_SECTIONS:
            found.append("few_sections")
        if not self.has_assessment:
            found.append("no_assessment")
        if not self.has_outcomes:
            found.append("no_outcomes")
        if not self.has_tags:
            found.append("no_tags")
        return found
