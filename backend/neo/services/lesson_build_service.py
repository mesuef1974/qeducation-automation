"""
بناء درس جديد كامل على المنصة من مواصفة معتمدة (المرحلة 10): إنشاء الدرس مخفيًا بتاريخه وحصته، ثم الكلمات والنتاجات
وأقسام الصفحات وعروض الأقسام والتقييم وملفات الملاحظات، ثم قراءة بعدية. كل خطوة تتحقق من وجود نتيجتها قبل الكتابة،
فإعادة التشغيل بعد انقطاع تستكمل ولا تكرر. الدرس يبقى مخفيًا: الظهور والنقاط من مرحلة النشر باعتماد المعلم.
"""
from collections.abc import Callable

from django.utils import timezone

from neo.domain import lesson_spec as ls
from neo.domain.redact import scrub
from neo.infrastructure.client import NeoClient, NotLoggedIn
from neo.infrastructure.parsers import parse_outcomes
from neo.models import PlatformClass, SyncRun
from neo.services import live, safety


class BuildError(ValueError):
    """طلب بناء غير قابل للتنفيذ (صف غير مسجّل، نتاج مجهول)؛ لا علاقة له بالمنصة."""


def describe(spec: ls.LessonSpec) -> list[str]:
    """ما سيُكتب بالترتيب، لتعرضه المعاينة على المعلم قبل أي كتابة."""
    lines = [f"درس «{spec.title}» في الصف {spec.lms_id}: {spec.day} الحصة {spec.period}"
             + (f"، قبل «{spec.before_title}»" if spec.before_title else "، في نهاية الدروس") + " (يُنشأ مخفيًا)",
             f"وصف: {spec.description[:80]}"]
    if spec.tags:
        lines.append("كلمات دلالية: " + "، ".join(spec.tags))
    if spec.outcome_codes:
        lines.append("نتاجات: " + "، ".join(spec.outcome_codes))
    lines += [f"قسم صفحة: {p.name}" for p in spec.pages]
    lines += [f"قسم عرض: {d.title} ← {d.path.name}" for d in spec.decks]
    if spec.quiz:
        lines.append(f"تقييم ذاتي التصحيح «{spec.quiz_name}»: {len(spec.quiz)} سؤالًا")
    lines += [f"ملف الملاحظات: {n.label} ← {n.path.name}" for n in spec.notes]
    return lines


class LessonBuildService:
    def build(self, spec: ls.LessonSpec, client_factory: Callable[[], NeoClient]) -> SyncRun:
        safety.require_writes_allowed()
        klass = PlatformClass.objects.filter(lms_id=spec.lms_id, active=True).select_related("plan").first()
        if klass is None:
            raise BuildError(f"الصف {spec.lms_id} غير مسجّل أو معطّل")
        steps: list[dict] = []
        run = SyncRun.objects.create(klass=klass, kind=SyncRun.Kind.CONTENT_APPLY, summary={"build": spec.title})
        stop, session_error, lesson_id = "", "", None
        try:
            with client_factory() as client:
                lesson_id = self._steps(spec, client, steps)
        except NotLoggedIn as exc:
            session_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - أول خطأ يوقف البناء، والموجود يبقى لإكمال لاحق
            stop = scrub(str(exc))[:500]
        run.summary = {"build": spec.title, "lesson": lesson_id, "steps": steps, "stopped": stop,
                       "error": "انتهت الجلسة" if session_error else ""}
        run.ok, run.finished_at = not stop and not session_error, timezone.now()
        run.save()
        if session_error:
            raise NotLoggedIn(session_error)
        return run

    def _steps(self, spec: ls.LessonSpec, c: NeoClient, steps: list[dict]) -> int:
        def done(name: str, state: str, note: str = "") -> None:
            steps.append({"step": name, "state": state, "note": note})
            live.step(f"{name}: {state}", len(steps), 8)

        lms = spec.lms_id
        before = None
        if spec.before_title:
            before = c.find_lesson_id(lms, spec.before_title, spec.academic_year)
            if before is None:
                raise BuildError(f"لا يوجد على المنصة درس «{spec.before_title}» ليُرتَّب قبله")
        live.stage(f"إنشاء الدرس «{spec.title}»", "build")
        lid, created = c.create_lesson(lms, spec.title, spec.description, spec.academic_year, (spec.day, spec.period), before)
        done("إنشاء الدرس", "أُنشئ مخفيًا" if created else "موجود", f"#{lid}")
        if not created and not c.lesson_is_open(lms, lid):  # شرط المعلم: مغلق = لا كتابة
            raise BuildError(safety.LOCKED_SKIP)
        if spec.tags:
            if c.lesson_tags(lms, lid):
                done("الكلمات الدلالية", "موجودة")
            else:
                c.set_lesson_tags(lms, lid, list(spec.tags))
                done("الكلمات الدلالية", "كُتبت")
        if spec.outcome_codes:
            if parse_outcomes(c.outcomes_html(lms, lid)):
                done("النتاجات", "موجودة")
            else:
                by_code = {o["code"]: o["id"] for o in c.available_outcomes(lms, lid)}
                if missing := [x for x in spec.outcome_codes if x not in by_code]:
                    raise BuildError(f"نتاجات غير متاحة للربط في الصف: {'، '.join(missing)}")
                c.link_outcomes(lms, lid, [by_code[x] for x in spec.outcome_codes])
                done("النتاجات", "رُبطت")
        existing = set(c.section_names(lms, lid))
        for page in spec.pages:
            if page.name in existing:
                done(f"قسم «{page.name}»", "موجود")
            else:
                c.add_page_section(lms, lid, page.name, page.html)
                done(f"قسم «{page.name}»", "أُضيف")
        for deck in spec.decks:
            if deck.title in existing:
                done(f"عرض «{deck.title}»", "موجود")
            else:
                c.add_file_section(lms, lid, deck.path, deck.title, spec.grade, spec.term)
                done(f"عرض «{deck.title}»", "رُفع")
        if spec.quiz:
            if spec.quiz_name in c.assessment_names(lms, lid):
                done("التقييم", "موجود")
            else:
                c.add_quiz(lms, lid, spec.quiz_name, list(spec.quiz))
                done("التقييم", "أُضيف")
        if spec.notes:
            c.add_notes_files(lms, lid, [(n.path, n.label) for n in spec.notes])
            done("ملفات الملاحظات", "اكتملت")
        if created and c.lesson_shown(lms, lid) is not False:
            raise BuildError("الدرس ظاهر للطلاب بعد البناء؛ أخفِه ثم راجع")
        return lid
