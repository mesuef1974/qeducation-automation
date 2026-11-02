"""
المهمة 3: نشر الدروس للطلاب.
- الرؤية: الدرس المؤرخ المخفي افتراضيًا يُجعل «ظاهرًا». المرجع تبويب «الرؤية» في كل درس، لا شارة «شخصى»
  في قائمة الدروس (ثبت أنها قد تبقى على درس ظاهر).
- الإنجاز: الدرس الذي لا يمنح نقاطًا («يمنح النقاط» غائبة) يُضاف له إجراء منح النقاط عند إنجازه.
السياسة: settings.NEO_PUBLISH_POLICY، ولكل صف أن يحدد لعبته ونقاطه (PlatformClass.points_game/points).
وجود اللعبة في الصف يُفحص عند الاقتراح وقبل التطبيق. الحالة تُقرأ من المنصة قبل كل كتابة؛
لا يُعدَّل إجراء قائم ولا يُكرَّر.
"""
from collections.abc import Callable
from dataclasses import dataclass, replace

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from neo.infrastructure.client import NeoClient, NotLoggedIn
from neo.models import PlatformClass, PlatformLesson, PublishProposal, SyncRun

ALREADY = "مطبّق على المنصة مسبقًا"


@dataclass(frozen=True)
class PublishPolicy:
    show_dated: bool = True
    points: int = 5            # 0 = لا تُضاف نقاط
    game: str = ""             # اسم لعبة النقاط في الصف؛ يختلف بين المواد
    notification: str = "Popup"  # Popup نافذة | Dropdown منسدلة


def policy(klass: PlatformClass) -> PublishPolicy:
    p = PublishPolicy(**getattr(settings, "NEO_PUBLISH_POLICY", {}))
    if klass.points_game:
        p = replace(p, game=klass.points_game)
    if klass.points is not None:
        p = replace(p, points=klass.points)
    return p


def game_error(p: PublishPolicy, games: list[str] | None) -> str:
    """سبب تعذّر منح النقاط في الصف، أو "" إن أمكن (games=None: لم تُفحص)."""
    if p.points <= 0:
        return ""
    if not p.game:
        return "لم تُحدَّد لعبة النقاط للصف (points_game)"
    if games is not None and p.game not in games:
        return f"اللعبة «{p.game}» غير موجودة في الصف؛ المتاح: {'، '.join(games) or 'لا شيء'}"
    return ""


def lesson_actions(lesson: PlatformLesson, p: PublishPolicy, points_ok: bool = True) -> tuple[bool, bool]:
    """منطق نقي: (إظهار، منح النقاط) المطلوبان لدرس."""
    return (p.show_dated and lesson.hidden and lesson.date is not None,
            points_ok and p.points > 0 and not lesson.awards_points)


class PublishService:
    # ------------------------------------------------------------- جلب

    def fetch(self, classes: list[PlatformClass], client_factory: Callable[[], NeoClient]) -> dict[int, list[str]]:
        """
        بعد جلب قائمة الدروس (SyncService.fetch): يقرأ تبويب «الرؤية» لكل درس مؤرخ ويحدّث PlatformLesson.hidden،
        ويعيد ألعاب النقاط المتاحة في كل صف.
        """
        dated = {k.pk: list(PlatformLesson.objects.filter(klass=k, date__isnull=False)
                            .values_list("pk", "lms_lesson_id")) for k in classes}
        any_lesson = {k.pk: PlatformLesson.objects.filter(klass=k).values_list("lms_lesson_id", flat=True).first()
                      for k in classes}
        shown, games = {}, {}
        with client_factory() as client:  # لا ORM هنا
            for k in classes:
                for pk, lid in dated[k.pk]:
                    shown[pk] = client.lesson_shown(k.lms_id, lid)
                games[k.pk] = client.points_games(k.lms_id, any_lesson[k.pk]) if any_lesson[k.pk] else []
        with transaction.atomic():
            for pk, s in shown.items():
                if s is not None:
                    PlatformLesson.objects.filter(pk=pk).update(hidden=not s)
        return games

    # ------------------------------------------------------------- اقتراح

    @transaction.atomic
    def plan(self, klass: PlatformClass, games: list[str] | None = None) -> SyncRun:
        p = policy(klass)
        points_error = game_error(p, games)
        PublishProposal.objects.filter(run__klass=klass, status__in=[
            PublishProposal.Status.PENDING, PublishProposal.Status.APPROVED,
        ]).update(status=PublishProposal.Status.REJECTED, error="استُبدل بعملية اقتراح أحدث")
        run = SyncRun.objects.create(klass=klass, kind=SyncRun.Kind.PUBLISH_PLAN)

        drafts, hidden_undated = [], []
        for lesson in PlatformLesson.objects.filter(klass=klass).order_by("position"):
            show, points = lesson_actions(lesson, p, points_ok=not points_error)
            if lesson.hidden and lesson.date is None:
                hidden_undated.append(lesson.position)
            if show or points:
                drafts.append(PublishProposal(run=run, lesson=lesson, show=show, add_points=points))
        PublishProposal.objects.bulk_create(drafts)
        run.summary = {
            "proposals": len(drafts),
            "show": sum(d.show for d in drafts),
            "add_points": sum(d.add_points for d in drafts),
            "hidden_undated": hidden_undated,
            "policy": {"show_dated": p.show_dated, "points": p.points, "game": p.game,
                       "notification": p.notification},
        }
        if points_error:
            run.summary["points_error"] = points_error
        run.ok, run.finished_at = not points_error, timezone.now()
        run.save()
        return run

    def approve(self, run_id: int) -> int:
        return PublishProposal.objects.filter(run_id=run_id, status=PublishProposal.Status.PENDING) \
            .update(status=PublishProposal.Status.APPROVED)

    # ------------------------------------------------------------- تطبيق

    def apply(self, run: SyncRun, client_factory: Callable[[], NeoClient], limit: int | None = None) -> SyncRun:
        p = policy(run.klass)
        lms_id = run.klass.lms_id
        items = list(run.publish_proposals.filter(status=PublishProposal.Status.APPROVED)
                     .select_related("lesson").order_by("lesson__position")[:limit])
        results: dict[int, tuple[str, str]] = {}
        state: dict[int, tuple[bool, bool]] = {}  # الدرس ← (ظاهر، يمنح النقاط) بعد التطبيق
        session_error = None
        with client_factory() as client:  # لا ORM هنا
            points_error = ""
            if any(prop.add_points for prop in items):
                points_error = game_error(p, client.points_games(lms_id, items[0].lesson.lms_lesson_id))
            for prop in items:
                lid = prop.lesson.lms_lesson_id
                try:
                    results[prop.pk], state[prop.lesson_id] = self._apply_one(client, lms_id, lid, prop, p,
                                                                              points_error)
                except NotLoggedIn as exc:
                    session_error = exc
                    break
                except Exception as exc:  # noqa: BLE001
                    results[prop.pk] = (PublishProposal.Status.FAILED, str(exc)[:400])
        log = self._record(run, items, results, state, session_error)
        if session_error:
            raise session_error
        return log

    @staticmethod
    def _apply_one(client: NeoClient, lms_id: int, lid: int, prop: PublishProposal, p: PublishPolicy,
                   points_error: str):
        done = False
        shown = client.lesson_shown(lms_id, lid)
        if shown is None:
            return (PublishProposal.Status.FAILED, "تبويب الرؤية غير متوقع"), (False, False)
        if prop.show and not shown:
            client.show_lesson(lms_id, lid)
            shown = client.lesson_shown(lms_id, lid)
            if not shown:
                return (PublishProposal.Status.FAILED, "لم يصبح ظاهرًا بعد الإظهار"), (False, False)
            done = True
        points = client.lesson_points_actions(lms_id, lid) > 0
        if prop.add_points and not points:
            if points_error:
                return (PublishProposal.Status.FAILED, points_error), (shown, False)
            client.add_points_action(lms_id, lid, p.points, p.game, p.notification)
            points = client.lesson_points_actions(lms_id, lid) > 0
            if not points:
                return (PublishProposal.Status.FAILED, "لم يظهر إجراء النقاط بعد الإضافة"), (shown, False)
            done = True
        status = PublishProposal.Status.APPLIED if done else PublishProposal.Status.SKIPPED
        return (status, "" if done else ALREADY), (shown, points)

    @transaction.atomic
    def _record(self, run, items, results, state, session_error) -> SyncRun:
        now = timezone.now()
        stats: dict[str, int] = {}
        for prop in items:
            if prop.pk not in results:
                continue
            prop.status, prop.error = results[prop.pk]
            if prop.status == PublishProposal.Status.APPLIED:
                prop.applied_at = now
            prop.save(update_fields=["status", "error", "applied_at"])
            if prop.lesson_id in state:
                shown, points = state[prop.lesson_id]
                PlatformLesson.objects.filter(pk=prop.lesson_id).update(hidden=not shown, awards_points=points)
            stats[prop.status] = stats.get(prop.status, 0) + 1
        summary = {"plan_run": run.pk, **stats}
        if session_error:
            summary["error"] = "انتهت الجلسة"
        return SyncRun.objects.create(
            klass=run.klass, kind=SyncRun.Kind.PUBLISH_APPLY, summary=summary, finished_at=timezone.now(),
            ok=not session_error and not stats.get(PublishProposal.Status.FAILED))
