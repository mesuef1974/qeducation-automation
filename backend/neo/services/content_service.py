"""
المرحلة 8: محرك المحتوى. يقترح للدروس الناقصة (من التدقيق) وصفًا وصورة بطاقة وقسم تهيئة،
ويعرضها للمعلم ليعدّلها ويعتمدها، ثم يطبّق المعتمد إضافةً فقط: لا يُعدَّل موجود ولا يُحذف.
التطبيق على درس واحد (lesson) أولًا، ثم التعميم.
"""
from collections.abc import Callable
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from curriculum.models import Lesson
from neo.domain import assessment, question_bank
from neo.domain import content as gen
from neo.infrastructure import tile_image
from neo.infrastructure.client import NeoClient, NotLoggedIn
from neo.infrastructure.parsers import parse_outcomes
from neo.models import ContentProposal, PlatformClass, PlatformLesson, SyncRun
from neo.services import live, safety

Kind = ContentProposal.Kind
# ما يُقترح لكل نقص يكشفه التدقيق
BY_ISSUE = {"no_description": Kind.DESCRIPTION, "generic_image": Kind.IMAGE, "few_sections": Kind.SECTION,
            "no_assessment": Kind.ASSESSMENT, "no_outcomes": Kind.OUTCOMES}


def _context(pl: PlatformLesson, outcomes: list[tuple[str, str]], previous: PlatformLesson | None) -> gen.LessonContext:
    plan_lesson = Lesson.objects.filter(plan=pl.klass.plan, code=pl.effective_code).select_related("unit").first()
    unit = plan_lesson.unit if plan_lesson else None
    # لا نتاجات على المنصة؟ أهداف موضوع الدرس من البنك، بلا رموز نتاجات
    goals = outcomes or [("", g) for g in question_bank.goals_for(pl.title)]
    return gen.LessonContext(
        position=pl.position, title=pl.title, unit_no=unit.unit_no if unit else None,
        unit_title=unit.title if unit else "", outcomes=tuple(goals),
        previous_title=previous.title if previous and previous.effective_code == pl.effective_code else "",
        sources=tuple(getattr(settings, "NEO_CONTENT_SOURCES", ())),
    )


class ContentService:
    # ------------------------------------------------------------- اقتراح

    def plan(self, classes: list[PlatformClass], client_factory: Callable[[], NeoClient]) -> list[SyncRun]:
        targets = {k.pk: list(PlatformLesson.objects.filter(klass=k, audit__isnull=False)
                              .exclude(audit__issues=[]).select_related("audit", "klass__plan").order_by("position"))
                   for k in classes}
        outcomes: dict[int, list[tuple[str, str]]] = {}
        available: dict[int, list[dict]] = {}  # نتاجات الصف المتاحة للربط، لدرس بلا نتاجات وله رموز في البنك
        with client_factory() as client:  # لا ORM هنا
            for k in classes:
                for i, pl in enumerate(targets[k.pk], 1):
                    live.step(f"الدرس {pl.position}. {pl.title}", i, len(targets[k.pk]))
                    outcomes[pl.lms_lesson_id] = parse_outcomes(client.outcomes_html(k.lms_id, pl.lms_lesson_id))
                    if not outcomes[pl.lms_lesson_id] and question_bank.outcomes_for(pl.title):
                        available[pl.lms_lesson_id] = client.available_outcomes(k.lms_id, pl.lms_lesson_id)
        return [self.record_plan(k, targets[k.pk], outcomes, available) for k in classes]

    @transaction.atomic
    def record_plan(self, klass: PlatformClass, lessons: list[PlatformLesson], outcomes: dict,
                    available: dict | None = None) -> SyncRun:
        ContentProposal.objects.filter(run__klass=klass, status__in=[
            ContentProposal.Status.PENDING, ContentProposal.Status.APPROVED,
        ]).update(status=ContentProposal.Status.REJECTED, error="استُبدل بعملية اقتراح أحدث")
        run = SyncRun.objects.create(klass=klass, kind=SyncRun.Kind.CONTENT_PLAN)
        all_lessons = {pl.position: pl for pl in PlatformLesson.objects.filter(klass=klass)}
        drafts, counts, unconfirmed = [], {}, []
        for pl in lessons:
            if not pl.match_sure:  # الخطوة 1: المحتوى يُبنى على موضوع الخطة، فلا اقتراح بمطابقة غير مؤكدة
                unconfirmed.append(safety.unconfirmed_label(pl))
                continue
            ctx = _context(pl, outcomes.get(pl.lms_lesson_id, []), all_lessons.get(pl.position - 1))
            for issue in pl.audit.issues:
                kind = BY_ISSUE.get(issue)
                if not kind or (kind == Kind.SECTION and "صفحة" in pl.audit.sections):  # له صفحة: النقص ليس التهيئة
                    continue
                payload = self._payload(kind, ctx, pl, (available or {}).get(pl.lms_lesson_id, []))
                if payload is None:  # لا بنك أسئلة أو نتاجات لموضوع الدرس: لا نختلق شيئًا
                    key = "بلا نتاجات في البنك" if kind == Kind.OUTCOMES else "بلا بنك أسئلة"
                    counts[key] = counts.get(key, 0) + 1
                    continue
                drafts.append(ContentProposal(run=run, lesson=pl, kind=kind, payload=payload))
                counts[kind.label] = counts.get(kind.label, 0) + 1
        ContentProposal.objects.bulk_create(drafts)
        run.summary = {"lessons": len(lessons), "proposals": len(drafts), "by_kind": counts,
                       "unconfirmed_match": unconfirmed,
                       "without_outcomes": [pl.position for pl in lessons if not outcomes.get(pl.lms_lesson_id)]}
        run.ok, run.finished_at = True, timezone.now()
        run.save()
        return run

    @staticmethod
    def _payload(kind: str, ctx: gen.LessonContext, pl: PlatformLesson, available: list[dict] = ()) -> dict | None:
        if kind == Kind.OUTCOMES:
            codes = question_bank.outcomes_for(pl.title)
            chosen = [o for o in available if o["code"] in codes]
            if not codes or len(chosen) != len(codes):
                return None
            return {"outcomes": chosen, "text": "\n".join(f"{o['code']} {o['text']}" for o in chosen)}
        if kind == Kind.ASSESSMENT:
            qs = question_bank.questions_for(pl.title)
            if not qs:
                return None
            return {"name": assessment.quiz_name(pl.position, pl.title), "text": assessment.to_text(qs),
                    "questions": [q.as_dict() for q in qs]}
        if kind == Kind.DESCRIPTION:
            return {"text": gen.description(ctx)}
        if kind == Kind.SECTION:
            return {"name": gen.INTRO_SECTION, "html": gen.intro_section_html(ctx)}
        spec = gen.tile_spec(ctx)
        path = settings.MEDIA_ROOT / "content" / f"{pl.lms_lesson_id}.png"
        tile_image.render(spec, path)
        return {**spec, "file": str(path.relative_to(settings.MEDIA_ROOT))}

    # ------------------------------------------------------------- اعتماد

    def approve(self, run_id: int, lesson: int | None = None) -> int:
        qs = ContentProposal.objects.filter(run_id=run_id, status=ContentProposal.Status.PENDING)
        if lesson:
            qs = qs.filter(lesson__lms_lesson_id=lesson)
        return safety.mark_approved(qs)

    # ------------------------------------------------------------- تطبيق

    def apply(self, run: SyncRun, client_factory: Callable[[], NeoClient], lesson: int | None = None) -> SyncRun:
        """يضيف المعتمد فقط، درسًا واحدًا إن حُدّد؛ يقرأ الحالة قبل كل إضافة فلا يكرر ما أُضيف."""
        qs = run.content_proposals.filter(status=ContentProposal.Status.APPROVED).select_related("lesson")
        if lesson:
            qs = qs.filter(lesson__lms_lesson_id=lesson)
        items = list(qs.order_by("lesson__position", "kind"))
        lms_id = run.klass.lms_id
        results: dict[int, tuple[str, str]] = {}
        session_error, stop = None, ""
        with client_factory() as client:  # لا ORM هنا
            for i, p in enumerate(items, 1):
                live.step(f"{p.get_kind_display()} · الدرس {p.lesson.position}", i, len(items))
                lid, pay = p.lesson.lms_lesson_id, p.payload
                try:
                    if p.kind == Kind.DESCRIPTION:
                        if client.lesson_description(lms_id, lid).strip():
                            results[p.pk] = (ContentProposal.Status.SKIPPED, "له وصف بالفعل")
                            continue
                        client.set_lesson_description(lms_id, lid, pay["text"])
                    elif p.kind == Kind.SECTION:
                        if pay["name"] in client.section_names(lms_id, lid):
                            results[p.pk] = (ContentProposal.Status.SKIPPED, "القسم موجود بالفعل")
                            continue
                        client.add_page_section(lms_id, lid, pay["name"], pay["html"])
                    elif p.kind == Kind.ASSESSMENT:
                        others = [n for n in client.assessment_names(lms_id, lid) if n != pay["name"]]
                        if others:  # تقييم بالاسم نفسه = محاولة سابقة انقطعت، فتُستكمل في add_quiz
                            results[p.pk] = (ContentProposal.Status.SKIPPED, "له تقييم بالفعل")
                            continue
                        client.add_quiz(lms_id, lid, pay["name"], assessment.from_dicts(pay["questions"]))
                    elif p.kind == Kind.OUTCOMES:
                        if parse_outcomes(client.outcomes_html(lms_id, lid)):
                            results[p.pk] = (ContentProposal.Status.SKIPPED, "له نتاجات بالفعل")
                            continue
                        client.link_outcomes(lms_id, lid, [o["id"] for o in pay["outcomes"]])
                    else:
                        if not client.tile_is_default(lms_id, lid):
                            results[p.pk] = (ContentProposal.Status.SKIPPED, "له صورة من المحتوى بالفعل")
                            continue
                        client.set_tile_picture(lms_id, lid, settings.MEDIA_ROOT / pay["file"], pay["color"])
                    results[p.pk] = (ContentProposal.Status.APPLIED, "")
                except NotLoggedIn as exc:
                    session_error = str(exc)
                    break
                except Exception as exc:  # noqa: BLE001 - الخطوة 5: أول خطأ غير متوقع يوقف التطبيق
                    results[p.pk] = (ContentProposal.Status.FAILED, str(exc)[:500])
                    stop = results[p.pk][1]
                    break
        return self._record_apply(run, items, results, session_error, stop)

    @transaction.atomic
    def _record_apply(self, run, items, results, session_error, stop: str = "") -> SyncRun:
        now, stats = timezone.now(), {}
        for p in items:
            if p.pk not in results:
                continue
            p.status, p.error = results[p.pk]
            if p.status == ContentProposal.Status.APPLIED:
                p.applied_at = now
            p.save(update_fields=["status", "error", "applied_at"])
            stats[p.status] = stats.get(p.status, 0) + 1
        summary = {"plan_run": run.pk, **stats}
        if session_error:
            summary["error"] = "انتهت الجلسة"
        if stop:
            summary.update(stopped=stop, not_attempted=sum(1 for p in items if p.pk not in results))
        run_apply = SyncRun.objects.create(
            klass=run.klass, kind=SyncRun.Kind.CONTENT_APPLY, summary=summary, finished_at=now,
            ok=not session_error and not stats.get(ContentProposal.Status.FAILED))
        if session_error:
            raise NotLoggedIn(session_error)
        return run_apply


def today() -> date:
    return timezone.localdate()
