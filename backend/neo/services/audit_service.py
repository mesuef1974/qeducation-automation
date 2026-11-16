"""
المرحلة 6: مدقق جودة الدروس (قراءة فقط). يقرأ بطاقة كل درس وصفحته، ويسجّل ما ينقصه ليجذب الطالب،
فيصبح معيار «جودة المحتوى» مقاسًا، وتعرف ما يحتاج إضافة (باعتمادك لاحقًا، وللناقص فقط).
"""
from collections import Counter
from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from neo.domain.quality import ISSUES, SECTION_KINDS, LessonQuality
from neo.domain.types import ParsedSection, ParsedTile
from neo.infrastructure.client import NeoClient
from neo.infrastructure.parsers import parse_sections, parse_tiles
from neo.models import LessonAudit, PlatformClass, PlatformLesson, SyncRun
from neo.services import live


class AuditService:
    def run(self, classes: list[PlatformClass], client_factory: Callable[[], NeoClient]) -> list[SyncRun]:
        lessons = {k.pk: list(PlatformLesson.objects.filter(klass=k)) for k in classes}
        pages: dict[int, tuple[list[ParsedTile], dict[int, list[ParsedSection]]]] = {}
        with client_factory() as client:  # لا ORM هنا
            for k in classes:
                tiles = parse_tiles(client.lesson_list_html(k.lms_id))
                sections, tags, quizzes = {}, {}, {}
                for i, pl in enumerate(lessons[k.pk], 1):
                    live.step(f"أقسام الدروس · {k.name}", i, len(lessons[k.pk]))
                    sections[pl.lms_lesson_id] = parse_sections(client.lesson_page_html(k.lms_id, pl.lms_lesson_id))
                    tags[pl.lms_lesson_id] = client.lesson_tags(k.lms_id, pl.lms_lesson_id)
                    if any(s.kind == "quiz" for s in sections[pl.lms_lesson_id]):
                        quizzes[pl.lms_lesson_id] = tuple(client.quiz_question_counts(k.lms_id, pl.lms_lesson_id))
                pages[k.pk] = (tiles, sections, tags, quizzes)
        return [self.record(k, lessons[k.pk], *pages[k.pk]) for k in classes]

    @transaction.atomic
    def record(self, klass: PlatformClass, lessons: list[PlatformLesson], tiles: list[ParsedTile],
               sections: dict[int, list[ParsedSection]], tags: dict[int, list[str]] | None = None,
               quizzes: dict[int, tuple[int, ...]] | None = None) -> SyncRun:
        now = timezone.now()
        by_id = {t.lms_lesson_id: t for t in tiles}
        issues, missing, complete = Counter(), [], 0
        for pl in lessons:
            tile = by_id.get(pl.lms_lesson_id)
            if tile is None:
                missing.append(pl.position)
                continue
            kinds = tuple(SECTION_KINDS.get(s.kind, s.kind) for s in sections.get(pl.lms_lesson_id, []))
            has_tags = bool(tags[pl.lms_lesson_id]) if tags and pl.lms_lesson_id in tags else True  # لم يُقرأ: لا نقص مُختلق
            q = LessonQuality(tile.image_default, pl.description, kinds, tile.has_outcomes, has_tags,
                              (quizzes or {}).get(pl.lms_lesson_id, ()))
            found = q.issues()
            issues.update(found)
            complete += not found
            LessonAudit.objects.update_or_create(lesson=pl, defaults={
                "image_default": tile.image_default, "sections": list(kinds), "has_outcomes": tile.has_outcomes,
                "has_tags": has_tags,
                "issues": found, "audited_at": now,
            })
        audited = len(lessons) - len(missing)
        return SyncRun.objects.create(
            klass=klass, kind=SyncRun.Kind.AUDIT, ok=not missing, finished_at=now,
            summary={"lessons": audited, "complete": complete,
                     "issues": {ISSUES[k]: n for k, n in issues.most_common()}, "not_in_list": missing},
        )
