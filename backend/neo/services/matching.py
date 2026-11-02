"""
مطابقة عناوين دروس المنصة ببنود الخطة الفصلية. منطق نقي بلا Django.
الدروس على المنصة مرتبة زمنيًا، فالمطابقة رتيبة (لا تعود إلى بند سابق) مع
تفضيل البند الأقرب عند تقارب الدرجات.
"""
import re
from difflib import SequenceMatcher

from neo.domain.types import Match, Target

THRESHOLD = 0.45
NEAR_TIE = 0.06

_DIACRITICS = re.compile(r"[ً-ْـ]")
_PART = re.compile(r"\s*(?:\(\s*ج?\s*\d+\s*\)|ج\s*\d+|\d+)\s*$")
_NON_WORD = re.compile(r"[^ء-يa-z\s]")
STOPWORDS = {"في", "من", "على", "الى", "او", "و", "ج"}


def normalize(text: str) -> str:
    t = _DIACRITICS.sub("", text)
    t = re.sub("[أإآ]", "ا", t).replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    t = _NON_WORD.sub(" ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def strip_part(title: str) -> str:
    """'إكمال المربع 3' / 'الاتصال(2)' / 'رسم منحنيات الدوال ج1' → العنوان بلا رقم الجزء."""
    prev = None
    while prev != title:
        prev, title = title, _PART.sub("", title).strip()
    return title


def _stem(tok: str) -> str:
    for p in ("وال", "بال", "لل", "ال"):
        if tok.startswith(p) and len(tok) - len(p) >= 3:
            return tok[len(p):]
    return tok


def tokens(text: str) -> set[str]:
    return {_stem(t) for t in normalize(text).split() if t not in STOPWORDS}


def score(platform_title: str, target_title: str) -> float:
    a, b = strip_part(platform_title), target_title
    ta, tb = tokens(a), tokens(b)
    overlap = len(ta & tb) / len(ta) if ta else 0.0
    ratio = SequenceMatcher(None, normalize(a), normalize(b)).ratio()
    return round(0.55 * overlap + 0.45 * ratio, 3)


def match_sequence(titles: list[str], targets: list[Target]) -> list[Match]:
    ordered = sorted(targets, key=lambda t: t.order)
    pointer = 0
    out = []
    for title in titles:
        scored = [(score(title, t.title), t) for t in ordered]
        ahead = [(s, t) for s, t in scored if t.order >= pointer]
        best = max((s for s, _ in ahead), default=0.0)
        if best >= THRESHOLD:
            # أقرب بند للأمام ضمن هامش التقارب
            s, chosen = next((s, t) for s, t in ahead if s >= best - NEAR_TIE)
        else:
            s, chosen = max(scored, key=lambda x: x[0], default=(0.0, None))
            if s < THRESHOLD:
                out.append(Match(None, s))
                continue
        pointer = max(pointer, chosen.order)
        out.append(Match(chosen.code, s))
    return out
