"""
عرض مراجعة بقالب مدرسة المعلم: يُستنسخ عرض درس مجاور (الماستر بشريط العنوان والأهداف والمصطلحات والقيمة)
وتُنسخ شرائحه النموذجية (العنوان، الأهداف، النشاط، الغلق، الواجب) بنصوص جديدة. لا شيء يُرسم من الصفر.
المعايير المستنتجة من عروض الدروس: شريحة عنوان بالبسملة والشريط، الأهداف، أمثلة، نشاط فردي/ثنائي،
«الدقيقة الواحدة» للغلق، ثم «الواجب: على منصة تعليم قطر».
"""
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Pt


class DeckTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Example:
    skill: str
    question: str
    solution: str


@dataclass(frozen=True)
class DeckContent:
    title: str
    goals: tuple[str, str]            # هدفان في شريط الأهداف الجانبي
    term: str                         # المصطلح (عربي | English)
    objectives: tuple[str, ...]       # أهداف شريحة «الأهداف»
    examples: tuple[Example, ...]
    activity: str
    fast: str
    closing_question: str
    closing_answer: str


# مواضع الشرائح النموذجية في عروض المدرسة (بدءًا من 0)
TITLE, GOALS, ACTIVITY_SOLO, HOMEWORK = 0, 1, 11, -1


def master_title(prs: Presentation) -> str:
    for sh in prs.slide_masters[0].shapes:
        if sh.name.startswith("Rounded Rectangle 44") and sh.has_text_frame:
            return sh.text_frame.text.strip()
    return ""


def _walk(shapes):
    for sh in shapes:
        yield sh
        if sh.shape_type == 6:
            yield from _walk(sh.shapes)


def _find(shapes, name: str):
    for sh in _walk(shapes):
        if sh.name == name:
            return sh
    raise DeckTemplateError(f"القالب بلا شكل «{name}»")


def set_text(shape, text: str, size: float | None = None) -> None:
    """يضع النص في أول مقطع بتنسيقه ويحذف الباقي، فيبقى تنسيق القالب."""
    tf = shape.text_frame
    paras = tf.paragraphs
    for extra in paras[1:]:
        extra._p.getparent().remove(extra._p)
    p = paras[0]
    runs = p.runs
    if not runs:
        p.add_run()
        runs = p.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    if size:
        runs[0].font.size = Pt(size)


def _clone(prs: Presentation, src):
    dst = prs.slides.add_slide(src.slide_layout)
    tree = dst.shapes._spTree
    for el in list(tree):
        if el.tag not in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            tree.remove(el)
    for el in src.shapes._spTree:
        if el.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            continue
        if el.iter(qn("p:contentPart")) and any(True for _ in el.iter(qn("p:contentPart"))):
            continue  # حبر/محتوى مرتبط بعلاقة خارجية: لا يُنسخ
        new = deepcopy(el)
        try:
            for blip in new.iter(qn("a:blip")):
                rid = blip.get(qn("r:embed"))
                if rid:
                    _, new_rid = dst.part.get_or_add_image_part(BytesIO(src.part.related_part(rid).blob))
                    blip.set(qn("r:embed"), new_rid)
        except KeyError:
            continue  # صورة بلا علاقة (بقايا قالب): يُترك الشكل
        tree.append(new)
    return dst


def _widen(shape, width: int) -> None:
    """العربية تُحاذى يمينًا: يبقى الحد الأيمن ويمتد الشكل يسارًا."""
    right = shape.left + shape.width
    shape.width = width
    shape.left = right - width


def build(template: Path, out: Path, c: DeckContent) -> None:
    prs = Presentation(str(template))
    if len(prs.slides) < 18:
        raise DeckTemplateError("القالب أقصر من عروض الدروس المعتادة")
    src = list(prs.slides)
    master = prs.slide_masters[0].shapes
    set_text(_find(master, "Rounded Rectangle 44"), c.title)
    set_text(_find(master, "Rectangle 4"), c.goals[0])
    set_text(_find(master, "Rectangle 2"), c.goals[1])
    set_text(_find(master, "Rectangle: Rounded Corners 3"), c.term)

    s = _clone(prs, src[TITLE])
    set_text(_find(s.shapes, "Ribbon: Tilted Down 3"), c.title)

    s = _clone(prs, src[GOALS])
    boxes = [_find(s.shapes, "Rectangle 2"), _find(s.shapes, "Rectangle 3")]
    for box, text in zip(boxes, c.objectives):
        set_text(box, f"{boxes.index(box) + 1}- {text}")
        _widen(box, 6_800_000)

    for n, ex in enumerate(c.examples, 1):
        s = _clone(prs, src[ACTIVITY_SOLO])
        set_text(_find(s.shapes, "Oval 3"), f"مهارة {n}")
        set_text(_find(s.shapes, "TextBox 7"), "مثال محلول.")
        set_text(_find(s.shapes, "TextBox 6"), f"{ex.skill}: {ex.question}", 22)
        solution = _find(s.shapes, "TextBox 8")
        set_text(solution, ex.solution, 22)
        _widen(solution, 8_400_000)

    s = _clone(prs, src[ACTIVITY_SOLO])
    set_text(_find(s.shapes, "Oval 3"), "ورقة عمل")
    set_text(_find(s.shapes, "TextBox 7"), "نشاط ثنائي.")
    set_text(_find(s.shapes, "TextBox 6"), c.activity, 22)
    set_text(_find(s.shapes, "TextBox 8"), c.fast, 22)

    s = _clone(prs, src[ACTIVITY_SOLO])
    set_text(_find(s.shapes, "Oval 3"), "الغلق")
    set_text(_find(s.shapes, "TextBox 7"), "الدقيقة الواحدة.")
    set_text(_find(s.shapes, "TextBox 6"), c.closing_question, 22)
    set_text(_find(s.shapes, "TextBox 8"), c.closing_answer, 22)

    _clone(prs, src[HOMEWORK])

    ids = prs.slides._sldIdLst
    for sld in list(ids)[:len(src)]:
        prs.part.drop_rel(sld.rId)
        ids.remove(sld)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))

