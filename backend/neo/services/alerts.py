"""
نصوص تنبيهات ويندوز بأحداث الأتمتة (الخطوة 0: الجلسة، والخطوة 9: الدورة، والإيقاف الآلي)؛ الإرسال في notify.
"""
from datetime import datetime

from django.utils import timezone

from neo.infrastructure import notify
from neo.models import Job

STAGES = ("dates", "assign", "publish")
WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def weekly(job: Job) -> bool:
    """ملخص الدورة بعد انتهائها، بزر يفتح «اليوم» حيث يبقى الملخص ثابتًا حتى يُقرأ."""
    if job.status == Job.Status.FAILED:
        return notify.toast("تعذّرت الدورة الأسبوعية", f"{job.get_error_kind_display()}: {job.error[:160]}",
                            ("افتح", notify.app_url()))
    classes = (job.report or {}).get("classes", {})
    held = sum(s.get("held", 0) for c in classes.values() for k, s in c.items() if k in STAGES)
    ready = [f"{name} (الأسبوع {c['prep'].get('week')})" for name, c in classes.items() if c.get("prep", {}).get("ok")]
    attention = (job.report or {}).get("attention", 0)
    title = "الدورة الأسبوعية تمت" + (f" · {attention} تحتاج نظرك" if attention else "")
    parts = [f"{held} اقتراحًا بانتظار اعتمادك" if held else "لا اقتراح بانتظار اعتمادك"]
    if ready:
        parts.append("حزم التحضير جاهزة: " + "، ".join(ready))
    return notify.toast(title, "؛ ".join(parts), ("افتح التقرير", notify.app_url()))


def late_cycle(start: datetime) -> bool:
    when = timezone.localtime(start)
    return notify.toast("الدورة الأسبوعية متأخرة",
                        f"موعدها {WEEKDAYS[when.weekday()]} {when:%H:%M} وكان الجهاز مطفأً؛ تعمل الآن.",
                        ("تابعها مباشرة", notify.app_url("live")))


def session_expired() -> bool:
    return notify.toast("انتهت جلسة منصة قطر للتعليم",
                        "تعذّر الدخول الصامت بالحساب الرسمي؛ سجّل الدخول ليكمل العامل ما ينتظره.",
                        ("سجّل الدخول", notify.app_url("?login=1")), key="session", every_s=3600)


def decline(items: list[dict]) -> bool:
    """الخطوة ٧: معيار بقي تحت هدفه يومين متتاليين، مع الخطوة التالية للأول."""
    names = "، ".join(f"{i['title']} ({i['value']}{'%' if i['unit'] == '%' else ' ' + i['unit']} من {i['target']})"
                      for i in items[:3])
    nxt = next((i["next"] for i in items if i["next"]), "")
    return notify.toast("معايير تحت هدفها يومين متتاليين", names + (f". التالي: {nxt}" if nxt else ""),
                        ("افتح بطاقة الأداء", notify.app_url()), key="decline", every_s=20 * 3600)


def halted(reason: str) -> bool:
    return notify.toast("أُوقفت الكتابة على المنصة", reason[:200], ("راجع السبب", notify.app_url()))
