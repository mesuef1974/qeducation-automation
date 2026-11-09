"""
الكلمات الدلالية للدرس (قرار المعلم 2026-11-09): عنوان الدرس بلا الترقيم، ثم وحدته من الخطة، ثم رموز نتاجاته.
نقية ومُعاد إنتاجها، ولا تختلق شيئًا: ما ليس في الخطة أو المنصة لا يدخل. المنصة تفصل الكلمات بالفاصلة
اللاتينية، فلا تحوي الكلمة فاصلة (لاتينية ولا عربية).
"""
import re

MAX_TAGS = 8


def clean(text: str) -> str:
    text = re.sub(r"[,،;؛\n\r]+", " ", text or "")
    text = re.sub(r"^\s*\d+(?:\.\d+)*[.\-–)]?\s+", "", text)  # ترقيم العنوان في أوله (يليه فراغ، فلا يمسّ 12A.3.5)
    return re.sub(r"\s+", " ", text).strip()


def build(title: str, unit_title: str, outcome_codes: list[str]) -> list[str]:
    tags: list[str] = []
    for raw in (title, unit_title, *outcome_codes):
        t = (raw or "").strip().strip(".") if raw in outcome_codes else clean(raw)
        if t and t not in tags:
            tags.append(t)
    return tags[:MAX_TAGS]


def parse_text(text: str) -> list[str]:
    """ما يكتبه المعلم في خانة التعديل (يفصل بينها فاصلة عربية أو لاتينية أو سطر) ← قائمة نظيفة."""
    out: list[str] = []
    for part in re.split(r"[,،\n]", text or ""):
        t = clean(part)
        if t and t not in out:
            out.append(t)
    return out[:MAX_TAGS]
