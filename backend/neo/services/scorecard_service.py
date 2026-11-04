"""
بطاقة الأداء: المعايير الثمانية بقيمها الحالية ومستهدفاتها، مما في قاعدة البيانات ومخزون domain/scorecard.
لا يلمس المنصة. اللقطة اليومية (snapshot) تحفظ القيم ليُقاس التحسن على خط الأساس (أول لقطة).
"""
from datetime import date

from django.db.models import Count, Q

from neo.domain.scorecard import CAPABILITIES, COMPLIANCE, LEVELS, TASKS
from neo.models import (
    LessonAudit,
    PlatformAssessment,
    PlatformClass,
    PlatformLesson,
    ScorecardSnapshot,
    SyncRun,
)

APPLY_KINDS = (SyncRun.Kind.APPLY, SyncRun.Kind.ASSIGN_APPLY, SyncRun.Kind.PUBLISH_APPLY)


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _avg_level(area: str | None = None) -> float:
    tasks = [t for t in TASKS if area in (None, t.area)]
    return round(sum(t.level for t in tasks) / len(tasks), 1)


def _criterion(key, title, value, target, unit="%", *, level=None, target_level=None, measured=True,
               detail="", next_step="") -> dict:
    return {"key": key, "title": title, "value": value, "target": target, "unit": unit, "level": level,
            "target_level": target_level, "measured": measured and value is not None, "detail": detail,
            "next": next_step}


def build(today: date) -> dict:
    classes = PlatformClass.objects.active()
    lessons = PlatformLesson.objects.filter(klass__in=classes).aggregate(
        total=Count("pk"), described=Count("pk", filter=~Q(description="")))
    assess = PlatformAssessment.objects.filter(klass__in=classes).aggregate(
        total=Count("pk"), given=Count("pk", filter=Q(given=True)))
    applies = SyncRun.objects.filter(klass__in=classes, kind__in=APPLY_KINDS).aggregate(
        total=Count("pk"), ok=Count("pk", filter=Q(ok=True)))
    audits = LessonAudit.objects.filter(lesson__klass__in=classes)
    audited = audits.count()
    complete = audits.filter(issues=[]).count()
    last_verify = [SyncRun.objects.filter(klass=k, kind=SyncRun.Kind.VERIFY).order_by("-pk").first() for k in classes]
    verify_ok = sum(1 for r in last_verify if r and r.ok)

    automated = sum(1 for t in TASKS if t.level >= 2)
    manual = sum(t.minutes for t in TASKS)
    now = sum(t.minutes * LEVELS[t.level][1] for t in TASKS)
    goal = sum(t.minutes * LEVELS[t.target][1] for t in TASKS)
    used = sum(1 for c in CAPABILITIES if c.used)
    enabled = sum(1 for c in CAPABILITIES if c.enabled)
    auto_caps = sum(1 for c in CAPABILITIES if c.automated)
    gates = sum(1 for _, ok in COMPLIANCE if ok)

    criteria = [
        _criterion("coverage", "تغطية الأتمتة", _pct(automated, len(TASKS)), 100,
                   level=_avg_level(), target_level=round(sum(t.target for t in TASKS) / len(TASKS), 1),
                   detail=f"{automated} من {len(TASKS)} مهمة متكررة عند المستوى 2 فأعلى",
                   next_step="الدورة الأسبوعية المجدولة ترفع المهام الإدارية إلى المستوى 4"),
        _criterion("time", "وقت المعلم", round(manual - now), round(manual - goal), "د/أسبوع",
                   detail=f"يدويًا {manual} دقيقة أسبوعيًا للصفين، والمتبقي الآن {round(now)} (تقدير أولي)",
                   next_step="قِس دقائقك الفعلية لكل مهمة أسبوعًا واحدًا لتصحيح التقدير"),
        _criterion("platform", "شمولية قدرات المنصة", _pct(used, len(CAPABILITIES)), 85,
                   detail=f"مستعملة {used} من {len(CAPABILITIES)} قدرة (26 تبويبًا و5 داخلية)؛ "
                          f"مفعّلة {enabled}، ومؤتمتة {auto_caps}. الاستعمال بإفادة المعلم",
                   next_step="استكشاف إعدادات الشارات وإنجاز الصف وأولياء الأمور (قراءة فقط)"),
        _criterion("engagement", "تفاعل الطالب", None, 80, level=_avg_level("students"), target_level=3,
                   measured=False, detail="لا يُجمع تقدّم الطلاب بعد (الدخول والإنجاز والتسليم)",
                   next_step="جامع تقدّم الطلاب من صفحات المنصة، محليًا فقط"),
        _criterion("mastery", "التحصيل والإتقان", _pct(assess["given"], assess["total"]), 100,
                   level=_avg_level("assess"), target_level=2,
                   detail=f"التقييمات المسندة {assess['given']} من {assess['total']}؛ الإتقان لا يُقاس بعد",
                   next_step="جمع نتائج التقييمات ثم الإتقان لكل وحدة"),
        _criterion("content", "جودة المحتوى",
                   _pct(complete, audited) if audited else _pct(lessons["described"], lessons["total"]), 100,
                   level=_avg_level("content"), target_level=2,
                   detail=(f"{complete} من {audited} درسًا مستوفٍ (صورة من المحتوى، ووصف، و3 أقسام فأكثر، وتقييم، ونتاج)"
                           if audited else f"{lessons['described']} من {lessons['total']} درسًا له وصف؛ لم يُدقَّق بعد"),
                   next_step="إضافة الناقص باعتمادك: البطاقة والوصف أولًا، ثم الأقسام والتقييم"),
        _criterion("reliability", "الموثوقية", _pct(applies["ok"], applies["total"]), 98,
                   detail=f"{applies['ok']} من {applies['total']} عملية تطبيق سليمة؛ "
                          f"آخر تحقق سليم في {verify_ok} من {len(last_verify)} صف",
                   next_step="فحص شكل المنصة قبل كل تشغيل، وتوقف عند عدد تغييرات غير مألوف"),
        _criterion("compliance", "الامتثال والحوكمة", _pct(gates, len(COMPLIANCE)), 100,
                   detail=f"{gates} من {len(COMPLIANCE)} شروط محققة"),
    ]
    return {
        "day": today.isoformat(),
        "criteria": criteria,
        "tasks": [{"key": t.key, "title": t.title, "area": t.area, "level": t.level, "target": t.target,
                   "minutes": t.minutes} for t in TASKS],
        "levels": {n: name for n, (name, _) in LEVELS.items()},
        "capabilities": [{"title": c.title, "group": c.group, "enabled": c.enabled, "used": c.used,
                          "automated": c.automated} for c in CAPABILITIES],
        "compliance": [{"title": t, "ok": ok} for t, ok in COMPLIANCE],
    }


def snapshot(today: date) -> tuple[ScorecardSnapshot, bool]:
    """لقطة اليوم؛ إعادة الطلب في اليوم نفسه تحدّثها ولا تكررها."""
    return ScorecardSnapshot.objects.update_or_create(day=today, defaults={"data": build(today)})


def history() -> dict:
    """خط الأساس (أول لقطة) وقيم كل معيار عبر اللقطات."""
    snaps = list(ScorecardSnapshot.objects.order_by("day"))
    return {
        "baseline": snaps[0].data if snaps else None,
        "series": [{"day": s.day.isoformat(), "values": {c["key"]: c["value"] for c in s.data["criteria"]}}
                   for s in snaps],
    }
