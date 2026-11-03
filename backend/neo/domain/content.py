"""
محرك المحتوى: يولّد لكل درس ناقص ما يُضاف إليه (وصف، وصورة بطاقة، وقسم تهيئة) من الخطة ونتاجات المنصة.
نقي ومُعاد الإنتاج: المدخلات نفسها تعطي النص نفسه، فيراجعه المعلم ويعدّله ويعتمده.
لا يلمس الموجود: ما له وصف أو صورة من المحتوى لا يُقترح له بديل.
"""
from dataclasses import dataclass, field

# لون ثابت لكل وحدة (ترتيبها في الخطة) ليعرف الطالب موقعه من المنهج
UNIT_COLORS = ("#8A1538", "#0594CC", "#2E7D4F", "#8558EE", "#D54407", "#1B6F8A", "#9A6200", "#5C4B8A")
INTRO_SECTION = "تهيئة الدرس"


@dataclass(frozen=True)
class LessonContext:
    position: int
    title: str
    unit_no: int | None
    unit_title: str
    outcomes: tuple[tuple[str, str], ...] = ()  # (الرمز، النص)
    previous_title: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)  # مصادر الصف (كتاب الطالب...)


def unit_color(unit_no: int | None) -> str:
    return UNIT_COLORS[(unit_no or 0) % len(UNIT_COLORS)]


def description(ctx: LessonContext) -> str:
    lines = ["في هذا الدرس ستتعلم أن:"]
    lines += [f"• {text}" for _, text in ctx.outcomes] or [f"• {ctx.title}"]
    if ctx.unit_title:
        lines.append(f"الوحدة {ctx.unit_no}: {ctx.unit_title}" if ctx.unit_no else ctx.unit_title)
    if ctx.previous_title:
        lines.append(f"ستحتاج إلى ما تعلمته في: {ctx.previous_title}")
    return "\n".join(lines)


def intro_section_html(ctx: LessonContext) -> str:
    goals = "".join(f"<li>{text}</li>" for _, text in ctx.outcomes) or f"<li>{ctx.title}</li>"
    parts = [f"<h3>أهداف الدرس</h3><ul>{goals}</ul>"]
    if ctx.previous_title:
        parts.append(f"<h3>قبل أن تبدأ</h3><p>راجع ما تعلمته في درس «{ctx.previous_title}».</p>")
    if ctx.sources:
        parts.append("<h3>مصادر مساندة</h3><ul>" + "".join(f"<li>{s}</li>" for s in ctx.sources) + "</ul>")
    codes = "، ".join(code for code, _ in ctx.outcomes)
    if codes:
        parts.append(f"<p><small>نتاجات التعلم: {codes}</small></p>")
    return "".join(parts)


# رسم يعبّر عن موضوع الدرس: أول كلمة مفتاحية تُصادف في العنوان تحدده، وإلا قطع مكافئ بسيط
MOTIFS = (
    ("بيانيا", "roots"),        # حل المعادلات بيانيًا: الجذور على محور x
    ("الرأس", "vertex"),        # صيغة الرأس: الرأس بإحداثييه
    ("القياسية", "intercept"),  # الصيغة القياسية: التقاطع مع محور y
    ("المميزات", "features"),   # المميزات الأساسية: الرأس ومحور التناظر والجذور
    ("متباين", "inequality"),   # المتباينات: المنطقة المظللة
    ("مثلثي", "sine"),          # الدوال المثلثية: موجة جيبية (قبل النهاية لأن العنوان يجمعهما)
    ("نهاي", "limit"),           # النهايات: منحنى بفجوة وسهما اقتراب
    ("الاتصال", "continuity"),  # الاتصال: قفزة في المنحنى
    ("المشتقة", "tangent"),     # المشتقة ومعدل التغير: مماس عند نقطة
    ("معدل التغير", "tangent"),
)


def motif_of(title: str) -> str:
    return next((m for key, m in MOTIFS if key in title), "parabola")


def tile_spec(ctx: LessonContext) -> dict:
    """ما تحتاجه صورة البطاقة؛ الرسم في طبقة البنية التحتية."""
    return {"color": unit_color(ctx.unit_no), "number": ctx.position, "title": ctx.title,
            "unit": f"الوحدة {ctx.unit_no}: {ctx.unit_title}" if ctx.unit_no else ctx.unit_title,
            "motif": motif_of(ctx.title)}
