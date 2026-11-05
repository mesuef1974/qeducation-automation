"""
استهلاك Claude (تبويب «الاستهلاك»). المصدر الوحيد «ميزان» على هذا الجهاز (NEO_MIZAN_URL)، قراءة فقط:

- صفحته الرئيسية فيها كتلة <script id="data-main"> بتوكنز كل يوم ونموذج وأصل طلب
  (أعمدة d، m رقم النموذج في models، g الأصل، t الرسائل، i الإدخال، cc كتابة الذاكرة، cr قراءتها، u المخرجات).
  «ميزان» يستورد سجلات Claude Code كل دقيقة ويحتفظ بها، فتبقى الأشهر التي حذف Claude ملفاتها.
- plan.json فيه لقطات الحصة: الأسبوعية (w، وتصفيرها wr)، وFable (fa، far)، والخمس ساعات (f، fr)، ومصدر كل لقطة.

لا يكتب على «ميزان» شيئًا ولا يطلب منه تحديثًا. إن تعذّر الوصول إليه رُفع MizanUnavailable برسالة واضحة.
"""
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone

TTL_S = 60  # «ميزان» يحدّث كل دقيقة
TIMEOUT_S = 8
ORIGINS = {"human": "إنسان", "peer": "جلسة أخرى", "scheduled": "مجدول", "sdk": "SDK", "task_notification": "إشعار مهمة",
           "system": "نظام", "sub": "وكيل فرعي", "unknown": "بلا أصل مسجّل"}
FAMILIES = ("Fable", "Mythos", "Opus", "Sonnet", "Haiku")
_DATA_MAIN = re.compile(r'<script[^>]*\bid="data-main"[^>]*>(.*?)</script>', re.S)
_cache: dict = {"at": 0.0, "data": None}


class MizanUnavailable(Exception):
    pass


def base() -> str:
    return getattr(settings, "NEO_MIZAN_URL", "http://127.0.0.1:8790").rstrip("/")


def _get(path: str) -> str:
    try:
        with urllib.request.urlopen(f"{base()}{path}", timeout=TIMEOUT_S) as r:  # noqa: S310 - عنوان محلي من الإعدادات
            return r.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MizanUnavailable(f"تعذّر الوصول إلى «ميزان» على {base()}: {exc}. شغّله ثم حدّث الصفحة.") from exc


def fetch(force: bool = False) -> dict:
    """بيانات «ميزان» الخام، مخزّنة دقيقة (TTL_S)؛ force = تجاوز المخزّن."""
    if not force and _cache["data"] and time.monotonic() - _cache["at"] < TTL_S:
        return _cache["data"]
    html = _get("/")
    m = _DATA_MAIN.search(html)
    if not m:
        raise MizanUnavailable("صفحة «ميزان» بلا كتلة data-main؛ تغيّرت صيغتها؟")
    try:
        main, plan = json.loads(m.group(1)), json.loads(_get("/plan.json"))
        cols = main["a"]["$cols"]
        rows = [dict(zip(cols, r, strict=False)) for r in main["a"]["rows"]]
    except (ValueError, KeyError, TypeError) as exc:
        raise MizanUnavailable(f"بيانات «ميزان» بصيغة غير متوقعة: {exc}") from exc
    data = {"models": main.get("models", []), "rows": rows, "plan": sorted(plan, key=lambda p: p.get("ts") or ""),
            "first_day": main.get("first_day"), "last_day": main.get("last_day"), "plan_label": main.get("plan_label"),
            "fetched_at": timezone.now()}
    _cache.update(at=time.monotonic(), data=data)
    return data


# ------------------------------------------------------------------ التجميع

def family(model: str) -> str:
    return next((f for f in FAMILIES if f.lower() in model.lower()), "أخرى")


def _row_tokens(r: dict) -> int:
    return (r.get("i") or 0) + (r.get("cc") or 0) + (r.get("cr") or 0) + (r.get("u") or 0)


def _sum(rows: list[dict]) -> dict:
    s = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "turns": 0}
    for r in rows:
        s["input"] += r.get("i") or 0
        s["cache_write"] += r.get("cc") or 0
        s["cache_read"] += r.get("cr") or 0
        s["output"] += r.get("u") or 0
        s["turns"] += r.get("t") or 0
    return {"tokens": s["input"] + s["cache_write"] + s["cache_read"] + s["output"], **s}


def _by(rows: list[dict], key) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def _families(rows: list[dict], name) -> list[dict]:
    by = {"Fable": []} | _by(rows, lambda r: family(name(r)))
    return sorted(({"family": f, **_sum(v)} for f, v in by.items()), key=lambda x: -x["tokens"])


def _day(r: dict) -> date:
    return date.fromisoformat(r["d"])


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _quota(plan: list[dict], rows: list[dict], name, pct: str, reset: str, fable: bool) -> dict | None:
    """
    آخر نسبة وموعد تصفيرها، ومعدل الحرق من لقطات النافذة نفسها في آخر 24 ساعة، والمتوقَّع عند التصفير،
    والتوكنز لكل 1% (توكنز النافذة حتى الآن ÷ النسبة). تقديرات تُعلَّم كذلك في الواجهة.
    """
    snaps = [p for p in plan if p.get(pct) is not None]
    if not snaps:
        return None
    last = snaps[-1]
    now, at, end = timezone.now(), _ts(last["ts"]), _ts(last.get(reset))
    same = [p for p in snaps if p.get(reset) == last.get(reset)]
    burn = None
    ref = next((p for p in same if at - _ts(p["ts"]) <= timedelta(hours=24)), None)
    if ref and (hours := (at - _ts(ref["ts"])).total_seconds() / 3600) >= 1:
        burn = (last[pct] - ref[pct]) / hours * 24
    projected = None
    if burn is not None and end:
        projected = min(100.0, last[pct] + burn * max(0.0, (end - now).total_seconds() / 86400))
    per_pct = None
    if end and last[pct] >= 1:
        start = timezone.localtime(end - timedelta(days=7)).date()
        win = [r for r in rows if _day(r) >= start and (not fable or family(name(r)) == "Fable")]
        per_pct = round(_sum(win)["tokens"] / last[pct]) if win else None
    return {"pct": last[pct], "reset": end, "at": at, "source": last.get("src"), "burn_per_day": burn,
            "projected": projected, "tokens_per_pct": per_pct, "stale": bool(end and end < now)}


def _monthly(rows: list[dict], first: date | None, today: date) -> list[dict]:
    if not first:
        return []
    by = _by(rows, lambda r: r["d"][:7])
    out, y, m = [], first.year, first.month
    while (y, m) <= (today.year, today.month):
        start = date(y, m, 1)
        end = date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)
        lo, hi = max(start, first), min(end, today)
        s, days = _sum(by.get(f"{y}-{m:02d}", [])), (hi - lo).days + 1
        out.append({"month": f"{y}-{m:02d}", "from": lo, "to": hi, "days": days, "partial": lo != start or hi != end,
                    "tokens": s["tokens"], "turns": s["turns"], "per_day": round(s["tokens"] / days)})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build(today: date | None = None, since: date | None = None, until: date | None = None,
          models: list[str] | None = None, force: bool = False) -> dict:
    """الملخص بمرشّحات الصفحة؛ لوحة الحدود والحصة لا يمسها المرشّح."""
    today = today or timezone.localdate()
    d = fetch(force)
    names = d["models"]
    name = lambda r: names[r["m"]] if isinstance(r.get("m"), int) and r["m"] < len(names) else "أخرى"  # noqa: E731
    rows = d["rows"]
    first = date.fromisoformat(d["first_day"]) if d.get("first_day") else None
    until = min(until or today, today)
    since = max(since or (today - timedelta(days=29)), first or since or today)
    picked = [r for r in rows if name(r) in models] if models else rows
    sel = [r for r in picked if since <= _day(r) <= until]
    week = _quota(d["plan"], rows, name, "w", "wr", False)
    week_start = timezone.localtime(week["reset"] - timedelta(days=7)).date() if week and week["reset"] else today - timedelta(days=6)
    win = lambda s: [r for r in rows if s <= _day(r) <= today]  # noqa: E731
    daily = _by(sel, lambda r: r["d"])
    series, day = [], since
    while day <= until:
        s = _sum(daily.get(day.isoformat(), []))
        series.append({"day": day, "tokens": s["tokens"], "turns": s["turns"]})
        day += timedelta(days=1)
    used = _by(rows, name)
    return {
        "today": today,
        "source": {"name": "ميزان", "url": base(), "fetched_at": d["fetched_at"], "first_day": d.get("first_day"),
                   "last_day": d.get("last_day"), "plan": d.get("plan_label"), "snapshots": len(d["plan"])},
        "filter": {"since": since, "until": until, "days": (until - since).days + 1, "models": models or []},
        "all_models": [{"model": n, "family": family(n)} for n in names if n in used],
        "quota": {"week": week, "fable": _quota(d["plan"], rows, name, "fa", "far", True),
                  "five_hour": _quota(d["plan"], rows, name, "f", "fr", False)},
        "panel": {"week": {"since": week_start, "all": _sum(win(week_start)),
                           "fable": _sum([r for r in win(week_start) if family(name(r)) == "Fable"])},
                  "month": {"since": today - timedelta(days=29), "all": _sum(win(today - timedelta(days=29))),
                            "families": _families(win(today - timedelta(days=29)), name)}},
        "totals": _sum(sel),
        "models": sorted(({"model": m, "family": family(m), **_sum(v)} for m, v in _by(sel, name).items()),
                         key=lambda x: -x["tokens"]),
        "families": _families(sel, name),
        "origins": sorted(({"origin": o, "label": ORIGINS.get(o, o), **_sum(v)} for o, v in _by(sel, lambda r: r.get("g") or "unknown").items()),
                          key=lambda x: -x["tokens"]),
        "daily": series,
        "monthly": _monthly(picked, first, today),
    }
