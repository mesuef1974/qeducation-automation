"""
استهلاك Claude (تبويب «الاستهلاك»).

الاستيراد: يقرأ سجلات الجلسات بصيغة Claude Code (*.jsonl) من مجلدات NEO_USAGE_DIRS (مجلد Claude على هذا
الجهاز، و backend/usage/ لملخصات الجلسات المُصدَّرة بـ tools/export_usage.py)، تزايديًا من موضع آخر قراءة
(UsageFile.offset)، ضمن مهلة زمنية (العامل كل 10 دقائق وهو خامل، و«حدّث الآن»)، فيُستأنف الباقي في المرة التالية.
الجداول مطبَّعة: مشروع ← جلسة ← خطوة ← نموذج وأدوات (UsageTurnTool). أرقام فقط، بلا أي نص من المحادثة.
الرسالة المكررة بمعرّفها تُعدّ مرة بأكبر أرقام أسطرها، والملف الذي أُعيدت كتابته يُقرأ من أوله، والسطر الناقص ينتظر اكتماله.

التجميع: اليوم والأسبوع (آخر 7 أيام) والشهر (آخر 30 يومًا)، وعائلات النماذج (Fable وOpus وSonnet وHaiku)، وكل يوم، وكل نموذج، وأين ذهب الاستهلاك، وكل جلسة.
الاستهلاك الفعلي بوحدة «رمز إدخال عادي»: قراءة سياق محفوظ ×0.1، وحفظ سياق جديد ×2، والمخرجات ×5.
"""
import hashlib
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, F, FloatField, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import Cast, TruncMonth
from django.utils import timezone

from neo.models import UsageFile, UsageModel, UsageProject, UsageSession, UsageTool, UsageTurn, UsageTurnTool

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

BATCH = 2000  # خطوات في كل حفظ؛ موضع القراءة يُحفظ بعد كل دفعة، فالملف الكبير لا يُعاد من أوله
BUDGET_S = 8.0


class _Refs:
    """معرّفات الصفوف المرجعية في الذاكرة طوال الاستيراد (مشروع، جلسة، نموذج، أداة)."""

    def __init__(self):
        self.projects, self.sessions, self.models, self.tools = {}, {}, {}, {}

    def project(self, name: str) -> UsageProject:
        if name not in self.projects:
            self.projects[name] = UsageProject.objects.get_or_create(name=name[:300])[0]
        return self.projects[name]

    def session(self, sid: str, project: UsageProject) -> int:
        if sid not in self.sessions:
            self.sessions[sid] = UsageSession.objects.get_or_create(session_id=sid[:100], defaults={"project": project})[0].pk
        return self.sessions[sid]

    def model(self, name: str) -> int:
        if name not in self.models:
            self.models[name] = UsageModel.objects.get_or_create(name=name[:100])[0].pk
        return self.models[name]

    def tool(self, name: str) -> int:
        if name not in self.tools:
            self.tools[name] = UsageTool.objects.get_or_create(name=name[:200], defaults={"group": tool_group(name)})[0].pk
        return self.tools[name]


def _record(line: bytes) -> dict | None:
    if b'"usage"' not in line:
        return None
    try:
        r = json.loads(line)
    except ValueError:
        return None
    m = r.get("message") or {}
    u = m.get("usage")
    if r.get("type") != "assistant" or not isinstance(u, dict) or not r.get("timestamp") or m.get("model") in (None, "<synthetic>"):
        return None
    key = f"{m['id']}:{r.get('requestId') or ''}" if m.get("id") else \
        hashlib.sha1(f"{r.get('sessionId')}|{r['timestamp']}|{json.dumps(u, sort_keys=True)}".encode()).hexdigest()
    content = m.get("content") if isinstance(m.get("content"), list) else []
    tools = defaultdict(int)
    for c in content:
        if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name"):
            tools[c["name"]] += 1
    try:
        at = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        return None
    return {"key": key[:200], "session": r.get("sessionId"), "at": at, "model": m["model"],
            "in": int(u.get("input_tokens") or 0), "cr": int(u.get("cache_read_input_tokens") or 0),
            "cw": int(u.get("cache_creation_input_tokens") or 0), "out": int(u.get("output_tokens") or 0), "tools": tools}


def _save(batch: list[dict], uf: UsageFile, refs: _Refs, default_session: str) -> int:
    """
    الرسالة الواحدة قد تُكتب في أكثر من سطر، وأولها قد يحمل رقمًا مؤقتًا أثناء كتابة الرد: يُؤخذ أكبر رقم لكل حقل،
    داخل الدفعة وبينها وبين ما حُفظ سابقًا (التحقق المستقل usage_verify يقارن بهذا).
    """
    merged: dict[str, dict] = {}
    for b in batch:
        e = merged.get(b["key"])
        if e is None:
            merged[b["key"]] = {**b, "tools": dict(b["tools"])}
        else:
            for k in ("in", "cr", "cw", "out"):
                e[k] = max(e[k], b[k])
            for name, n in b["tools"].items():
                e["tools"][name] = max(e["tools"].get(name, 0), n)
    existing = {t.key: t for t in UsageTurn.objects.filter(key__in=list(merged))}
    rows, uses, grown = [], [], []
    for key, b in merged.items():
        if t := existing.get(key):
            new = (max(t.input_tokens, b["in"]), max(t.cache_read, b["cr"]), max(t.cache_write, b["cw"]),
                   max(t.output_tokens, b["out"]))
            if new != (t.input_tokens, t.cache_read, t.cache_write, t.output_tokens):
                t.input_tokens, t.cache_read, t.cache_write, t.output_tokens = new
                grown.append(t)
            continue
        rows.append(UsageTurn(
            key=key, file=uf, session_id=refs.session(b["session"] or default_session, uf.project),
            model_id=refs.model(b["model"]), at=b["at"], day=timezone.localtime(b["at"]).date(),
            input_tokens=b["in"], cache_read=b["cr"], cache_write=b["cw"], output_tokens=b["out"]))
        uses.append(b["tools"])
    UsageTurn.objects.bulk_update(grown, ["input_tokens", "cache_read", "cache_write", "output_tokens"], batch_size=500)
    UsageTurn.objects.bulk_create(rows, batch_size=500)  # SQLite يعيد المعرّفات
    UsageTurnTool.objects.bulk_create([UsageTurnTool(turn_id=t.pk, tool_id=refs.tool(name), uses=n)
                                       for t, tools in zip(rows, uses, strict=True) for name, n in tools.items()],
                                      batch_size=500)
    return len(rows)


def _import_file(path: Path, root: Path, refs: _Refs, deadline: float) -> tuple[int, bool]:
    """يعيد (خطوات جديدة، اكتمل الملف؟)."""
    st = path.stat()
    rel = path.relative_to(root).parts
    uf = UsageFile.objects.filter(path=str(path)).first() or UsageFile(
        path=str(path), project=refs.project(rel[0] if len(rel) > 1 else ""))
    if uf.pk and uf.size == st.st_size and uf.mtime == st.st_mtime and uf.offset >= st.st_size:
        return 0, True
    if st.st_size < uf.offset:  # أُعيدت كتابة الملف: من أوله، والمكرر يُتجاهل بمفتاحه
        uf.offset = 0
    uf.save()
    default_session = path.parent.name if "subagents" in rel else path.stem
    new, batch, done = 0, [], True
    with path.open("rb") as f:
        f.seek(uf.offset)
        pos = uf.offset
        for line in f:
            if not line.endswith(b"\n"):  # سطر لم يكتمل بعد
                break
            pos += len(line)
            if rec := _record(line):
                batch.append(rec)
            if len(batch) >= BATCH:
                new += _save(batch, uf, refs, default_session)
                batch, uf.offset = [], pos
                uf.save(update_fields=["offset"])
                if time.monotonic() > deadline:
                    done = False
                    break
        if batch:
            new += _save(batch, uf, refs, default_session)
        uf.offset = pos
    uf.size, uf.mtime, uf.imported_at = (st.st_size, st.st_mtime, timezone.now()) if done else (0, 0, timezone.now())
    uf.save()
    return new, done


def import_all(budget_s: float | None = BUDGET_S) -> dict:
    """يستورد الجديد من كل المجلدات ضمن المهلة (None = بلا مهلة)؛ pending = بقي ما يُستأنف لاحقًا."""
    deadline = time.monotonic() + budget_s if budget_s is not None else float("inf")
    refs, files, new, pending = _Refs(), 0, 0, False
    for root in dirs():
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.jsonl")):
            if files and time.monotonic() > deadline:  # كل استدعاء يتقدم ملفًا على الأقل
                pending = True
                break
            try:
                n, done = _import_file(p, root, refs, deadline)
            except OSError:
                continue
            files, new = files + 1, new + n
            pending = pending or not done
    return {"files": files, "new": new, "pending": pending}


# ------------------------------------------------------------------ التجميع

def _eff():
    f = lambda name: Cast(F(name), FloatField())  # noqa: E731
    return f("input_tokens") + W_READ * f("cache_read") + W_WRITE * f("cache_write") + W_OUT * f("output_tokens")


def _sum(qs: QuerySet) -> dict:
    a = qs.aggregate(eff=Sum(_eff()), i=Sum("input_tokens"), r=Sum("cache_read"), w=Sum("cache_write"),
                     o=Sum("output_tokens"), n=Count("pk"), s=Count("session", distinct=True))
    i, r, w, o = (a[k] or 0 for k in "irwo")
    return {"effective": round(a["eff"] or 0), "tokens": i + r + w + o, "input": i, "cache_read": r, "cache_write": w,
            "output": o, "turns": a["n"], "sessions": a["s"]}


def _models(qs: QuerySet) -> list[dict]:
    rows = qs.values("model__name").annotate(eff=Sum(_eff()), i=Sum("input_tokens"), r=Sum("cache_read"),
                                             w=Sum("cache_write"), o=Sum("output_tokens"), n=Count("pk"),
                                             s=Count("session", distinct=True)).order_by("-eff")
    return [{"model": x["model__name"], "effective": round(x["eff"] or 0), "tokens": x["i"] + x["r"] + x["w"] + x["o"],
             "input": x["i"], "cache_read": x["r"], "cache_write": x["w"], "output": x["o"], "turns": x["n"],
             "sessions": x["s"]} for x in rows]


def _groups(qs: QuerySet) -> list[dict]:
    """قراءة السياق وحفظه على كل الخطوات، والمخرجات على أدوات الخطوة بالتساوي (أو «الردود» إن لم تكن أداة)."""
    a = qs.aggregate(read=Sum(F("input_tokens") + W_READ * Cast(F("cache_read"), FloatField())), write=Sum("cache_write"),
                     reply=Sum("output_tokens", filter=Q(tool_uses__isnull=True)))
    g = defaultdict(float)
    g[CONTEXT_READ] = a["read"] or 0
    g[CONTEXT_WRITE] = W_WRITE * (a["write"] or 0)
    g[REPLY] = W_OUT * (a["reply"] or 0)
    uses = UsageTurnTool.objects.filter(turn__in=qs).values_list("turn_id", "tool__group", "uses", "turn__output_tokens")
    per_turn = defaultdict(list)
    for turn, group, n, out in uses.iterator():
        per_turn[turn].append((group, n, out))
    for items in per_turn.values():
        total = sum(n for _, n, _ in items)
        for group, n, out in items:
            g[group] += W_OUT * out * n / total
    return sorted(({"name": k, "effective": round(v)} for k, v in g.items() if v), key=lambda x: -x["effective"])


FAMILIES = (("fable", "Fable"), ("mythos", "Mythos"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"))


def family(model: str) -> str:
    m = model.lower()
    return next((label for key, label in FAMILIES if key in m), "أخرى")


def _families(models: list[dict]) -> list[dict]:
    """استهلاك كل عائلة نماذج من صفوف _models (Fable ظاهر دائمًا ولو صفرًا)."""
    by = {"Fable": {"family": "Fable", "effective": 0, "tokens": 0, "turns": 0, "models": []}}
    for m in models:
        f = by.setdefault(family(m["model"]), {"family": family(m["model"]), "effective": 0, "tokens": 0, "turns": 0,
                                                "models": []})
        f["effective"] += m["effective"]
        f["tokens"] += m["tokens"]
        f["turns"] += m["turns"]
        f["models"].append(m["model"])
    return sorted(by.values(), key=lambda x: -x["effective"])


def _daily(qs: QuerySet, since: date, until: date) -> list[dict]:
    rows = {r["day"]: r for r in qs.values("day").annotate(
        eff=Sum(_eff()), n=Count("pk"), t=Sum(F("input_tokens") + F("cache_read") + F("cache_write") + F("output_tokens")))}
    out, d = [], since
    while d <= until:
        r = rows.get(d, {})
        out.append({"day": d, "effective": round(r.get("eff") or 0), "tokens": r.get("t") or 0, "turns": r.get("n") or 0})
        d += timedelta(days=1)
    return out


def _monthly(qs: QuerySet, first_day: date | None, today: date) -> list[dict]:
    """كل شهر ميلادي من أول يوم في البيانات حتى اليوم: الرموز والمعدل اليومي، والشهر الأول والجاري جزئيان."""
    if not first_day:
        return []
    rows = {(r["m"].year, r["m"].month): r for r in qs.annotate(m=TruncMonth("day")).values("m").annotate(
        eff=Sum(_eff()), n=Count("pk"), t=Sum(F("input_tokens") + F("cache_read") + F("cache_write") + F("output_tokens")))}
    out, y, m = [], first_day.year, first_day.month
    while (y, m) <= (today.year, today.month):
        start = date(y, m, 1)
        end = (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1))
        lo, hi = max(start, first_day), min(end, today)
        r, days = rows.get((y, m), {}), (hi - lo).days + 1
        out.append({"month": f"{y}-{m:02d}", "from": lo, "to": hi, "days": days, "partial": lo != start or hi != end,
                    "tokens": r.get("t") or 0, "effective": round(r.get("eff") or 0), "turns": r.get("n") or 0,
                    "per_day": round((r.get("t") or 0) / days)})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _panel(qs: QuerySet, since: date, today: date) -> dict:
    """سطر في لوحة الحدود: كل النماذج وFable وحده، بلا مرشّح النماذج (كما تعدّ الخطة)."""
    win = qs.filter(day__range=(since, today))
    fable = win.filter(model__name__icontains="fable")
    return {"since": since, "all": _sum(win), "fable": _sum(fable), "families": _families(_models(win))}


def build(today: date | None = None, since: date | None = None, until: date | None = None,
          models: list[str] | None = None, session: str | None = None) -> dict:
    """
    الملخص بمرشّحات الصفحة: النطاق (since..until، افتراضه آخر 30 يومًا) والنماذج (افتراضه كلها).
    لوحة الحدود (الأسبوع وآخر 30 يومًا، كل النماذج وFable) لا يمسها المرشّح.
    """
    today = today or timezone.localdate()
    all_ = UsageTurn.objects.all()
    first = all_.aggregate(m=Min("at"))["m"]
    first_day = timezone.localtime(first).date() if first else None
    until = min(until or today, today)
    since = since or (today - timedelta(days=29))
    if first_day and since < first_day:
        since = first_day
    picked = all_.filter(model__name__in=models) if models else all_
    sel = picked.filter(day__range=(since, until))
    latest = all_.order_by("-at").values_list("session__session_id", flat=True).first()
    session = session or latest
    sess = all_.filter(session__session_id=session)
    names = list(all_.values("model__name").annotate(last=Max("at")).order_by("-last").values_list("model__name", flat=True))
    files = UsageFile.objects.all()
    return {
        "today": today, "session": session,
        "weights": {"cache_read": W_READ, "cache_write": W_WRITE, "output": W_OUT},
        "sources": [{"path": str(d), "found": d.is_dir(), "files": files.filter(path__startswith=str(d)).count()}
                    for d in dirs()],
        "imported_at": files.aggregate(m=Max("imported_at"))["m"], "first": first,
        "filter": {"since": since, "until": until, "days": (until - since).days + 1, "models": models or []},
        "all_models": [{"model": n, "family": family(n)} for n in names],
        "panel": {"week": _panel(all_, today - timedelta(days=6), today),
                  "month": _panel(all_, today - timedelta(days=29), today)},
        "session_total": _sum(sess),
        "totals": _sum(sel),
        "models": (ms := _models(sel)),
        "families": _families(ms),
        "groups": _groups(sel),
        "daily": _daily(sel, since, until),
        "monthly": _monthly(picked, first_day, today),
    }
