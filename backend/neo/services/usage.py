"""
استهلاك Claude (تبويب «الاستهلاك»).

الاستيراد: يقرأ سجلات الجلسات بصيغة Claude Code (*.jsonl) من مجلدات NEO_USAGE_DIRS (مجلد Claude على هذا
الجهاز، و backend/usage/ لملخصات الجلسات المُصدَّرة بـ tools/export_usage.py)، تزايديًا من موضع آخر قراءة
(UsageFile.offset)، ويحفظ كل خطوة للنموذج في UsageTurn: الوقت والنموذج والرموز وأسماء الأدوات فقط، بلا نص.
الرسالة المكررة بمعرّفها تُعدّ مرة، والملف الذي أُعيدت كتابته يُقرأ من أوله.

التجميع: اليوم والأسبوع (آخر 7 أيام) والشهر (منذ أوله)، وكل يوم، وكل نموذج، وأين ذهب الاستهلاك، وكل جلسة.
الاستهلاك الفعلي بوحدة «رمز إدخال عادي»: قراءة سياق محفوظ ×0.1، وحفظ سياق جديد ×2، والمخرجات ×5.
"""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, F, FloatField, Max, Min, QuerySet, Sum
from django.db.models.functions import Cast
from django.utils import timezone

from neo.models import UsageFile, UsageTurn

W_READ, W_WRITE, W_OUT = 0.1, 2.0, 5.0
CONTEXT_READ, CONTEXT_WRITE, REPLY = "قراءة السياق (التعليمات والمحادثة)", "حفظ سياق جديد", "الردود والتفكير"


def tool_group(name: str) -> str:
    if name.startswith("mcp__claude-in-chrome__"):
        return "متصفح Chrome"
    if name.startswith(("mcp__remote-devices__Claude_Browser", "mcp__Claude_Browser")):
        return "المتصفح المدمج"
    if name.startswith("mcp__remote-devices__") or name in ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "NotebookEdit"):
        return "العمل على الملفات والأوامر"
    if name.startswith("mcp__memory") or name == "Projects":
        return "الذاكرة وملفات المشروع"
    if name in ("WebSearch", "WebFetch"):
        return "بحث الويب"
    if name == "Agent":
        return "وكلاء فرعيون"
    if name.startswith("mcp__"):
        return "موصلات أخرى"
    return "أدوات التنظيم"


def dirs() -> list[Path]:
    return [Path(d).expanduser() for d in getattr(settings, "NEO_USAGE_DIRS", [])]


# ------------------------------------------------------------------ الاستيراد

def _turn(r: dict, uf: UsageFile) -> UsageTurn | None:
    m = r.get("message") or {}
    u = m.get("usage")
    if r.get("type") != "assistant" or not u or not r.get("timestamp") or m.get("model") in (None, "<synthetic>"):
        return None
    at = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
    session = r.get("sessionId") or uf.session_id
    key = f"{m['id']}:{r.get('requestId') or ''}" if m.get("id") else \
        hashlib.sha1(f"{session}|{r['timestamp']}|{json.dumps(u, sort_keys=True)}".encode()).hexdigest()
    content = m.get("content") if isinstance(m.get("content"), list) else []
    return UsageTurn(
        key=key[:200], file=uf, session_id=session[:100], at=at, day=timezone.localtime(at).date(), model=m["model"][:100],
        input_tokens=u.get("input_tokens") or 0, cache_read=u.get("cache_read_input_tokens") or 0,
        cache_write=u.get("cache_creation_input_tokens") or 0, output_tokens=u.get("output_tokens") or 0,
        tools=[c.get("name", "") for c in content if isinstance(c, dict) and c.get("type") == "tool_use"])


def _import_file(path: Path, root: Path) -> int:
    st = path.stat()
    uf, _ = UsageFile.objects.get_or_create(path=str(path), defaults={
        "session_id": path.stem[:100], "project": (path.parent.name if path.parent != root else "")[:300]})
    if uf.size == st.st_size and uf.mtime == st.st_mtime:
        return 0
    if st.st_size < uf.offset:  # أُعيدت كتابة الملف: من أوله، والمكرر يُتجاهل بمفتاحه
        uf.offset = 0
    added = []
    with path.open("rb") as f:
        f.seek(uf.offset)
        data = f.read()
    end = data.rfind(b"\n") + 1  # سطر لم يكتمل بعد يُقرأ في المرة القادمة
    for line in data[:end].splitlines():
        if b'"usage"' not in line:
            continue
        try:
            t = _turn(json.loads(line), uf)
        except (ValueError, KeyError, TypeError):
            continue
        if t:
            added.append(t)
    before = UsageTurn.objects.count()
    UsageTurn.objects.bulk_create(added, ignore_conflicts=True, batch_size=500)
    uf.offset += end
    uf.size, uf.mtime, uf.imported_at = st.st_size, st.st_mtime, timezone.now()
    uf.save()
    return UsageTurn.objects.count() - before


def import_all() -> dict:
    """يستورد الجديد من كل المجلدات؛ يعيد عدد الملفات والخطوات الجديدة."""
    files = new = 0
    for root in dirs():
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.jsonl")):
            try:
                n = _import_file(p, root)
            except OSError:
                continue
            files += 1
            new += n
    return {"files": files, "new": new}


# ------------------------------------------------------------------ التجميع

def _eff():
    f = lambda name: Cast(F(name), FloatField())
    return f("input_tokens") + W_READ * f("cache_read") + W_WRITE * f("cache_write") + W_OUT * f("output_tokens")


def _sum(qs: QuerySet) -> dict:
    a = qs.aggregate(eff=Sum(_eff()), i=Sum("input_tokens"), r=Sum("cache_read"), w=Sum("cache_write"),
                     o=Sum("output_tokens"), n=Count("pk"), s=Count("session_id", distinct=True))
    i, r, w, o = (a[k] or 0 for k in "irwo")
    return {"effective": round(a["eff"] or 0), "tokens": i + r + w + o, "input": i, "cache_read": r, "cache_write": w,
            "output": o, "turns": a["n"], "sessions": a["s"]}


def _models(qs: QuerySet) -> list[dict]:
    return [{"model": m, **_sum(qs.filter(model=m))} for m in
            qs.values_list("model", flat=True).distinct().order_by()]


def _groups(qs: QuerySet) -> list[dict]:
    g = defaultdict(float)
    for i, r, w, o, tools in qs.values_list("input_tokens", "cache_read", "cache_write", "output_tokens", "tools").iterator():
        g[CONTEXT_READ] += i + W_READ * r
        g[CONTEXT_WRITE] += W_WRITE * w
        if tools:
            for name in tools:
                g[tool_group(name)] += W_OUT * o / len(tools)
        else:
            g[REPLY] += W_OUT * o
    return sorted(({"name": k, "effective": round(v)} for k, v in g.items() if v), key=lambda x: -x["effective"])


def _by_eff(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda x: -x["effective"])


def build(today: date | None = None, days: int = 30, session: str | None = None) -> dict:
    today = today or timezone.localdate()
    all_ = UsageTurn.objects.all()
    week_start, month_start = today - timedelta(days=6), today.replace(day=1)
    latest = all_.order_by("-at").values_list("session_id", flat=True).first()
    session = session or latest
    periods = {"today": all_.filter(day=today), "week": all_.filter(day__range=(week_start, today)),
               "month": all_.filter(day__range=(month_start, today)), "session": all_.filter(session_id=session)}
    daily = {r["day"]: r for r in all_.filter(day__range=(today - timedelta(days=days - 1), today)).values("day")
             .annotate(eff=Sum(_eff()), n=Count("pk"), o=Sum("output_tokens"),
                       t=Sum(F("input_tokens") + F("cache_read") + F("cache_write") + F("output_tokens")))}
    series = []
    for d in (today - timedelta(days=i) for i in range(days - 1, -1, -1)):
        r = daily.get(d, {})
        series.append({"day": d, "effective": round(r.get("eff") or 0), "tokens": r.get("t") or 0,
                       "turns": r.get("n") or 0, "output": r.get("o") or 0})
    sessions = []
    for s in all_.values("session_id").annotate(first=Min("at"), last=Max("at")).order_by("-last")[:30]:
        qs = all_.filter(session_id=s["session_id"])
        uf = UsageFile.objects.filter(turns__session_id=s["session_id"]).first()
        sessions.append({"session": s["session_id"], "project": uf.project if uf else "", "first": s["first"],
                         "last": s["last"], "models": sorted(set(qs.values_list("model", flat=True))), **_sum(qs)})
    files = UsageFile.objects.all()
    return {
        "today": today, "week_start": week_start, "month_start": month_start, "session": session,
        "weights": {"cache_read": W_READ, "cache_write": W_WRITE, "output": W_OUT},
        "sources": [{"path": str(d), "found": d.is_dir(), "files": files.filter(path__startswith=str(d)).count()}
                    for d in dirs()],
        "imported_at": files.aggregate(m=Max("imported_at"))["m"],
        "first": all_.aggregate(m=Min("at"))["m"], "last": all_.aggregate(m=Max("at"))["m"],
        "totals": {k: _sum(v) for k, v in periods.items()},
        "models": {k: _by_eff(_models(v)) for k, v in periods.items()},
        "groups": {k: _groups(v) for k, v in periods.items()},
        "daily": series, "sessions": sessions,
    }
