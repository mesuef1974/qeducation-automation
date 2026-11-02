"""
توليد حصص الفصل من الجدول الدراسي وأسابيع الخطة، واقتراح تواريخ للدروس غير المؤرخة.
منطق نقي بلا Django.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from neo.domain.types import ProposalDraft, Slot, Target

FLAG_UNMATCHED = "غير مطابق للخطة"
FLAG_OUTSIDE = "خارج أسابيع البند في الخطة"
FLAG_PAST = "تاريخ ماضٍ"
FLAG_SHARED = "حصة مشتركة مع الدرس السابق"


@dataclass(frozen=True)
class WeekSpan:
    week_no: int
    start: date  # الأحد
    teaching: bool


@dataclass(frozen=True)
class LessonState:
    lesson_id: int
    date: date | None
    period: int | None
    code: str | None


def build_slots(weeks: list[WeekSpan], timetable: list[tuple[int, int]]) -> list[Slot]:
    slots = []
    for w in weeks:
        if not w.teaching:
            continue
        for weekday, period in timetable:
            offset = (weekday - 6) % 7  # الأحد=0 ... الخميس=4
            if offset <= 4:
                slots.append(Slot(w.start + timedelta(days=offset), period, w.week_no))
    return sorted(slots, key=lambda s: s.key)


def propose_dates(lessons: list[LessonState], targets: dict[str, Target], slots: list[Slot],
                  today: date) -> tuple[list[ProposalDraft], list[int]]:
    """
    يمر على الدروس بترتيبها. الدرس المؤرخ يحجز موقعه ويُقدّم المؤشر؛ غير المؤرخ يأخذ أول حصة
    بعد المؤشر ضمن أسابيع بنده في الخطة، وإلا أول حصة بعد المؤشر مع تنبيه.
    يعيد (الاقتراحات، دروس لم تتسع لها حصص الفصل).
    """
    keys = [s.key for s in slots]
    occupied = {(ls.date, ls.period) for ls in lessons if ls.date}
    # حد أعلى لكل درس: موقع أقرب درس مؤرخ بعده؛ لا يُقترح تاريخ يكسر الترتيب
    bound, upper = [], len(slots)
    for ls in reversed(lessons):
        bound.append(upper)
        if ls.date:
            upper = bisect_right(keys, (ls.date, (ls.period or 1) - 1))
    bound.reverse()

    pointer = -1
    last_dated: Slot | None = None
    out: list[ProposalDraft] = []
    overflow: list[int] = []
    for i, ls in enumerate(lessons):
        if ls.date:
            pointer = max(pointer, bisect_right(keys, (ls.date, ls.period or 99)) - 1)
            last_dated = Slot(ls.date, ls.period or 0, slots[pointer].week_no if pointer >= 0 else 0)
            continue
        free = [j for j in range(pointer + 1, bound[i]) if keys[j] not in occupied]
        flags = []
        target = targets.get(ls.code) if ls.code else None
        idx = None
        if target:
            idx = next((j for j in free if slots[j].week_no in target.weeks), None)
            if idx is None and free:
                flags.append(FLAG_OUTSIDE)
        else:
            flags.append(FLAG_UNMATCHED)
        if idx is None and free:
            idx = free[0]
        if idx is None:
            if bound[i] < len(slots) and last_dated:
                # محصور بين درسين مؤرخين بلا حصة شاغرة: يشارك حصة الدرس السابق
                flags.append(FLAG_SHARED)
                if last_dated.date < today:
                    flags.append(FLAG_PAST)
                out.append(ProposalDraft(ls.lesson_id, last_dated, flags))
            else:
                overflow.append(ls.lesson_id)
            continue
        slot = slots[idx]
        if slot.date < today:
            flags.append(FLAG_PAST)
        out.append(ProposalDraft(ls.lesson_id, slot, flags))
        pointer = idx
    return out, overflow
