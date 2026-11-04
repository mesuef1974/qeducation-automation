"""
حزمة التحضير الأسبوعية: لأي صف وأي أسبوع من الخطة، مجلد على سطح المكتب فيه لكل درس ملف التحضير والعرض
وورقة العمل من «ملاحظات المعلم» وعروض أقسامه، وملفات التحضير معدّلة، وصف الرسالة الأسبوعية.

قراءة فقط من المنصة. الترتيب: ORM أولًا (الخطة والدروس والجدول)، ثم المتصفح للاكتشاف والتنزيل إلى الذاكرة
المؤقتة، ثم الكتابة بعد إغلاقه (Playwright يمنع ORM داخل سياقه). الأصل يبقى في الذاكرة المؤقتة ويُنسخ منه ثم
يُعدَّل دائمًا، فالتشغيل الثاني ينتج الملفات نفسها، ولا يُحذف من مجلد المعلم شيء.
"""
import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from curriculum.models import CalendarEvent, ScheduleEntry, Week
from neo.domain import weekly_pack as wp
from neo.domain.types import FileLink
from neo.infrastructure import docx_prep, office
from neo.infrastructure.client import NotLoggedIn, PlatformError
from neo.models import PlatformAssessment, PlatformClass, SyncRun
from neo.services import live
from neo.services.matching import normalize
from neo.services.scheduling import WeekSpan
from neo.services.sync_service import NO_MATCH

MESSAGE_FILE = "الرسالة الأسبوعية.txt"
HOLIDAY, TESTS = "إجازة", "اختبارات"


class PackStopped(ValueError):
    """الحزمة تحتاج قرار المعلم قبل بنائها (رسالة PackError)."""


@dataclass
class _Found:
    """ما اكتُشف لدرس على المنصة (بلا ORM): روابط الملاحظات وعروض الأقسام، ومسارها في الذاكرة المؤقتة."""
    notes: list[FileLink] = field(default_factory=list)
    sections: list[tuple[str, FileLink]] = field(default_factory=list)
    cached: dict[str, Path] = field(default_factory=dict)  # FileLink.key ← المسار
    downloaded: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _code(e: ScheduleEntry) -> str:
    return e.lesson.code if e.lesson else f"{e.activity_type}#{e.unit.unit_no if e.unit else 0}"


class PrepService:
    def __init__(self, policy: dict | None = None):
        self.policy = {**settings.NEO_PREP, **(policy or {})}
        self.cache = Path(self.policy["cache_dir"])

    # ------------------------------------------------------------- 1. الخطة (ORM)

    def select(self, klass: PlatformClass, week_no: int) -> tuple[list[wp.PackLesson], Week]:
        plan = klass.plan
        week = Week.objects.filter(plan=plan, week_no=week_no).first()
        if week is None:
            raise PackStopped(f"لا يوجد أسبوع {week_no} في خطة {plan}.")
        entries = [wp.PlanEntry(e.week.week_no, e.seq, _code(e), e.lesson.title if e.lesson else e.title, e.periods,
                                e.lesson is not None)
                   for e in ScheduleEntry.objects.filter(plan=plan).select_related("week", "lesson", "unit")]
        lessons = [wp.LessonRef(pl.lms_lesson_id, pl.position, pl.title,
                                "" if pl.effective_code == NO_MATCH else pl.effective_code, pl.date, pl.period)
                   for pl in klass.lessons.exclude(override_code=NO_MATCH)]
        days_off = set()
        for ev in CalendarEvent.objects.filter(plan=plan, event_type=HOLIDAY, start_date__lte=week.end_date,
                                               end_date__gte=week.start_date):
            d = max(ev.start_date, week.start_date)
            while d <= min(ev.end_date, week.end_date):
                days_off.add(d)
                d += timedelta(days=1)
        span = WeekSpan(week.week_no, week.start_date, week.week_type == Week.Type.TEACHING)
        timetable = list(klass.slots.values_list("weekday", "period"))
        try:
            return wp.select_week(entries, lessons, span, timetable, days_off), week
        except wp.PackError as exc:
            raise PackStopped(str(exc)) from exc

    # ------------------------------------------------------------- 2. المنصة (بلا ORM)

    def _cache_path(self, link: FileLink) -> Path:
        return self.cache / "files" / link.key

    def _fetch(self, client, lms_id: int, pack: list[wp.PackLesson]) -> dict[int, _Found]:
        pages = self.cache / "pages" / str(lms_id)  # صفحات الملاحظات والأقسام كما وصلت، للتشخيص
        pages.mkdir(parents=True, exist_ok=True)

        def keep(name: str, html: str) -> None:
            (pages / name).write_text(html, encoding="utf-8")

        found = {}
        live.stage("قراءة الملاحظات والأقسام وتنزيل الملفات")
        for i, pl in enumerate(pack, 1):
            live.step(f"الدرس {pl.position}: ملاحظات المعلم وأقسام العرض", i, len(pack))
            f = found[pl.lms_lesson_id] = _Found()
            notes, html = client.lesson_notes_files(lms_id, pl.lms_lesson_id)
            keep(f"notes_{pl.lms_lesson_id}.html", html)
            f.notes = [x for x in notes if wp.note_role(x) != "other"]
            seen = {x.key for x in f.notes}
            for sec, links in client.section_files(lms_id, pl.lms_lesson_id, keep):
                for x in links:
                    if x.key not in seen:
                        seen.add(x.key)
                        f.sections.append((sec.title, x))
            for link in [*f.notes, *(x for _, x in f.sections)]:
                path = self._cache_path(link)
                if not (path.exists() and path.stat().st_size):
                    try:
                        size = client.download(link.url, path)
                        f.downloaded.append(link.key)
                        live.emit("file", f"نُزّل: {link.name}", op="download", size=size, lesson=pl.position)
                    except NotLoggedIn:
                        raise
                    except PlatformError as exc:
                        f.errors.append(f"{link.name}: {exc}")
                        live.emit("error", f"تعذّر تنزيل {link.name}: {exc}", lesson=pl.position)
                        continue
                else:
                    live.emit("file", f"من الذاكرة المؤقتة: {link.name}", op="cache", cached=True, lesson=pl.position)
                f.cached[link.key] = path
        return found

    # ------------------------------------------------------------- 3. الكتابة

    def _dest_root(self) -> Path:
        return Path(self.policy["dest_dir"]) if self.policy.get("dest_dir") else office.desktop_dir()

    @staticmethod
    def _unique(name: str, used: set[str]) -> str:
        stem, dot, ext = name.rpartition(".")
        out, i = name, 2
        while out in used:
            out, i = f"{stem} ({i}){dot}{ext}", i + 1
        used.add(out)
        return out

    def _write_lesson(self, pl: wp.PackLesson, f: _Found, lesson_dir: Path, base: docx_prep.PrepFields) -> dict:
        fields = docx_prep.PrepFields(base.year_from, base.teacher, pl.day_name, pl.date, base.section, pl.period)
        files, used, texts = [], set(), []
        roles = [wp.note_role(x) for x in f.notes]
        for link, role in zip(f.notes, roles):
            if link.key not in f.cached:
                continue
            name = self._unique(wp.note_file_name(link), used)
            dst, src = lesson_dir / name, f.cached[link.key]
            entry = {"name": name, "role": role, "file": link.key,
                     "source": "تنزيل" if link.key in f.downloaded else "الذاكرة المؤقتة"}
            if link.ext == "docx":
                try:
                    res = docx_prep.prepare_docx(src, dst, fields, worksheet=role == "worksheet")
                except Exception as exc:  # noqa: BLE001 - ملف تالف لا يوقف بقية الحزمة
                    f.errors.append(f"{name}: تعذّر تعديله ({exc})")
                    live.emit("error", f"تعذّر تعديل {name}: {exc}", lesson=pl.position)
                    continue
                live.emit("file", f"عُدّل: {name}", op="edit", lesson=pl.position)
                entry["changes"] = res.as_dict()
                paras = docx_prep.paragraphs(dst)
                if role == "prep":
                    texts += paras
                elif wp.topic_key(pl.plan_title) not in normalize(" ".join(paras)).replace(" ", ""):
                    entry["note"] = "عنوان ورقة العمل لا يذكر موضوع الدرس؛ تحقّق أنها تخصه"
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            files.append(entry)
        for i, (title, link) in enumerate(((t, x) for t, x in f.sections if x.key in f.cached), start=1):
            name = wp.section_file_name(i, title, link)
            dst = lesson_dir / wp.SECTIONS_DIR / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f.cached[link.key], dst)
            files.append({"name": f"{wp.SECTIONS_DIR}/{name}", "role": "section", "file": link.key,
                          "section": title, "source": "تنزيل" if link.key in f.downloaded else "الذاكرة المؤقتة"})
        missing = [label for role, label in (("prep", "ملف التحضير"), ("presentation", "عرض الدرس"),
                                             ("worksheet", "ورقة العمل")) if role not in roles]
        if not f.sections:
            missing.append("عروض الأقسام")
        produced = {lesson_dir / x["name"] for x in files}
        extra = sorted(str(p.relative_to(lesson_dir)) for p in lesson_dir.rglob("*")
                       if p.is_file() and p not in produced and not p.name.endswith((".tmp", ".part")))
        return {"files": files, "missing": missing, "extra": extra, "texts": texts}

    # ------------------------------------------------------------- 4. التحقق

    def _word_check(self, docs: list[tuple[str, Path, wp.PackLesson]], base: docx_prep.PrepFields,
                    pdf_dir: Path) -> list[dict]:
        """ملف واحد من كل قالب: يفتحه Word ويصدّره PDF، ثم يُفحص الرأس والتذييل وجدول المتابعة كما يعرضها."""
        out = []
        for i, (template, path, pl) in enumerate(docs, 1):
            live.step(f"فتح Word: قالب «{template}» وتصديره PDF", i, len(docs))
            item = {"template": template, "file": path.name}
            try:
                seen = office.word_read_and_export(path, pdf_dir / f"{path.stem}.pdf")
            except office.OfficeUnavailable as exc:
                out.append({**item, "ok": None, "note": f"تعذّر فتح Word: {exc}"})
                continue
            stories = " ".join(seen.get("stories", []) + seen.get("headers", []) + seen.get("footers", []))
            tables = " ".join(seen.get("tables", []))
            problems = []
            if old := docx_prep.STALE_YEAR.findall(stories + tables):
                problems.append(f"بقي عام قديم فيما يعرضه Word ({len(old)} موضعًا)")
            years = {m.group(1) for m in docx_prep.YEAR_PAIR.finditer(stories)
                     if int(m.group(3)) == int(m.group(1)) + 1}
            if years - {str(base.year_from)}:
                problems.append(f"عام دراسي غير الحالي فيما يعرضه Word: {sorted(years)}")
            for label, text in (("اسم المعلم", base.teacher), ("اليوم والتاريخ", pl.date_text),
                                ("الشعبة", base.section)):
                if text and text not in tables:
                    problems.append(f"لم يظهر {label} «{text}» في الجداول")
            out.append({**item, "ok": not problems, "problems": problems, "pdf": str(pdf_dir / f"{path.stem}.pdf"),
                        "years_seen": sorted(years)})
        return out

    # ------------------------------------------------------------- التشغيل

    def run(self, klass: PlatformClass, week_no: int, factory) -> SyncRun:
        run = SyncRun.objects.create(klass=klass, kind=SyncRun.Kind.PREP, summary={"week": week_no})
        try:
            return self._run(run, klass, week_no, factory)
        except Exception as exc:
            run.summary = {**run.summary, "error": str(exc)}
            run.ok, run.finished_at = False, timezone.now()
            run.save()
            raise

    def _run(self, run: SyncRun, klass: PlatformClass, week_no: int, factory) -> SyncRun:
        plan = klass.plan
        live.stage(f"اختيار دروس الأسبوع {week_no} من الخطة · {klass.name}")
        pack, week = self.select(klass, week_no)
        live.step(f"الدروس {pack[0].position}–{pack[-1].position}: {wp.topics_text(pack)}", len(pack), len(pack))
        section = wp.class_section(klass.name)
        year_from = int(plan.academic_year.split("-")[0])
        base = docx_prep.PrepFields(year_from, self.policy.get("teacher", ""), "", week.start_date, section, 0)
        ids = [pl.lms_lesson_id for pl in pack]
        finals = [a.title for a in PlatformAssessment.objects.filter(klass=klass, lms_lesson_id__in=ids)
                  if "ختامي" in normalize(a.title)]
        tests = [(e.title, e.start_date, e.end_date) for e in CalendarEvent.objects.filter(
            plan=plan, event_type=TESTS, start_date__lte=week.end_date, end_date__gte=week.start_date)]
        book = wp.book_for(plan.grade_level, plan.term_no, plan.tracks)
        root = self._dest_root()  # قبل المتصفح: خطأ هنا لا يكلّف طلبات على المنصة

        with factory() as client:
            found = self._fetch(client, klass.lms_id, pack)

        week_dir = root / wp.week_folder(self.policy["folder"], week_no, section)
        lessons, texts, errors, first_of_template = [], [], [], {}
        live.stage(f"نسخ الملفات وتعديل التحضيرات في {week_dir.name}")
        for i, pl in enumerate(pack, 1):
            live.step(f"الدرس {pl.position}: {pl.day_name} {pl.date_text} · ح{pl.period}", i, len(pack))
            f = found[pl.lms_lesson_id]
            lesson_dir = week_dir / pl.folder
            lesson_dir.mkdir(parents=True, exist_ok=True)
            done = self._write_lesson(pl, f, lesson_dir, base)
            texts += done.pop("texts")
            errors += [f"{pl.position}: {e}" for e in f.errors]
            for x in done["files"]:
                if x["role"] == "prep" and "changes" in x:
                    first_of_template.setdefault(x["changes"]["template"], (lesson_dir / x["name"], pl))
            lessons.append({
                "position": pl.position, "title": pl.title, "part": f"{pl.plan_title} {pl.part}", "code": pl.code,
                "folder": pl.folder, "day": pl.day_name, "date": pl.date.isoformat(), "period": pl.period,
                "platform_date": pl.platform_date.isoformat() if pl.platform_date else None,
                "platform_period": pl.platform_period, "platform_differs": pl.platform_differs,
                "downloaded": len(f.downloaded), **done,
            })

        live.stage("صف الرسالة الأسبوعية والتحقق")
        pages, unknown_pages = wp.week_pages(book, pack)
        row = wp.message_row(section, pack, pages, wp.homework_text(wp.book_exercises(texts), len(finals)),
                             wp.tests_text(tests))
        (week_dir / MESSAGE_FILE).write_text(wp.message_tsv(row), encoding="utf-8-sig")

        produced = [week_dir / x["folder"] / f["name"] for x in lessons for f in x["files"]]
        stale = {str(p.relative_to(week_dir)): s for p in produced if p.suffix == ".docx"
                 if (s := docx_prep.stale_years(p))}
        hashes = {str(p.relative_to(week_dir)): _sha(p) for p in produced}
        hashes[MESSAGE_FILE] = _sha(week_dir / MESSAGE_FILE)
        previous = SyncRun.objects.filter(klass=klass, kind=SyncRun.Kind.PREP, ok=True,
                                          summary__week=week_no).exclude(pk=run.pk).first()
        same = None
        if previous and previous.summary.get("hashes"):
            same = previous.summary["hashes"] == hashes
        checks = []
        if self.policy.get("word_check"):
            checks = self._word_check([(t, p, pl) for t, (p, pl) in first_of_template.items()], base,
                                      self.cache / "verify" / week_dir.name)

        run.summary = {
            "week": week_no, "week_range": [week.start_date.isoformat(), week.end_date.isoformat()],
            "folder": str(week_dir), "section": section, "lessons": lessons,
            "message": {"header": list(wp.MESSAGE_HEADER), "row": row, "file": MESSAGE_FILE},
            "pages_unknown": unknown_pages, "final_assessments": finals,
            "downloads": sum(x["downloaded"] for x in lessons), "files": len(produced),
            "stale_years": stale, "word_check": checks, "hashes": hashes, "same_as_previous": same,
            "platform_differs": [x["position"] for x in lessons if x["platform_differs"]],
            "errors": errors, "teacher_missing": not base.teacher,
        }
        run.ok = not errors and not stale and all(c.get("ok") is not False for c in checks)
        live.step(f"المجلد جاهز: {len(produced)} ملفًا" + (" · مطابق للتشغيل السابق" if same else ""))
        run.finished_at = timezone.now()
        run.save()
        return run
