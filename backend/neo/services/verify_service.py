"""
المهمة 4: التحقق من منظور الطالب (قراءة فقط).
يفتح الصف «كطالب عام» ويقارن الدروس التي يراها بما يُتوقَّع بعد المهام 1-3:
- الدرس الظاهر ذو التاريخ الماضي يجب أن يراه الطالب، وإلا فهو «مفقود» وتفشل العملية.
- درس اليوم يكفي ظهوره في لوحة «اليوم»؛ بطاقته تظهر عند موعد حصته.
- الدرس المستقبلي لا يُطلب ظهوره؛ المنصة تكشفه عند موعده، ويُذكر للمتابعة.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from neo.infrastructure.client import NeoClient
from neo.infrastructure.parsers import parse_student_lessons
from neo.models import PlatformClass, PlatformLesson, SyncRun


@dataclass
class VisibilityReport:
    seen: int = 0
    missing: list[int] = field(default_factory=list)            # ماضٍ ظاهر لا يراه الطالب
    today_missing: list[int] = field(default_factory=list)      # درس اليوم غائب حتى عن لوحة «اليوم»
    unexpected: list[int] = field(default_factory=list)         # مخفي عندنا ويراه الطالب
    scheduled: list[int] = field(default_factory=list)          # مستقبلي ستكشفه المنصة
    undated: list[int] = field(default_factory=list)            # بلا تاريخ ولا يراه الطالب
    hidden: list[int] = field(default_factory=list)             # مخفي عندنا («شخصى») ولا يراه الطالب

    @property
    def ok(self) -> bool:
        return not (self.missing or self.today_missing)


def compare(lessons: list[PlatformLesson], tiles: set[int], today_ids: set[int], today: date) -> VisibilityReport:
    """منطق نقي: المواضع (position) في كل قائمة."""
    r = VisibilityReport(seen=len(tiles))
    for pl in sorted(lessons, key=lambda x: x.position):
        lid, seen = pl.lms_lesson_id, pl.lms_lesson_id in tiles
        if pl.hidden:
            (r.unexpected if seen else r.hidden).append(pl.position)
        elif pl.date is None:
            if not seen:
                r.undated.append(pl.position)
        elif pl.date < today and not seen:
            r.missing.append(pl.position)
        elif pl.date == today and not (seen or lid in today_ids):
            r.today_missing.append(pl.position)
        elif pl.date > today and not seen:
            r.scheduled.append(pl.position)
    return r


class VerifyService:
    def run(self, classes: list[PlatformClass], client_factory: Callable[[], NeoClient],
            today: date) -> list[SyncRun]:
        with client_factory() as client:  # لا ORM هنا
            pages = {k.pk: client.student_view_html(k.lms_id) for k in classes}
        return [self.record(k, *parse_student_lessons(pages[k.pk]), today) for k in classes]

    @transaction.atomic
    def record(self, klass: PlatformClass, tiles: set[int], today_ids: set[int], today: date) -> SyncRun:
        r = compare(list(PlatformLesson.objects.filter(klass=klass)), tiles, today_ids, today)
        return SyncRun.objects.create(
            klass=klass, kind=SyncRun.Kind.VERIFY, ok=r.ok, finished_at=timezone.now(),
            summary={"today": today.isoformat(), "seen_by_student": r.seen, "missing_past": r.missing,
                     "missing_today": r.today_missing, "hidden_but_seen": r.unexpected,
                     "scheduled_future": len(r.scheduled), "next_scheduled": r.scheduled[:3],
                     "undated_unseen": r.undated, "hidden_unseen": r.hidden},
        )
