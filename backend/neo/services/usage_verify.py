"""
تحقق مستقل من أرقام «الاستهلاك» (مهمة usage_verify في العامل): يعدّ ملفات السجل الأصلية بكود منفصل عن الاستيراد
(neo/services/usage.py) ثم يقارن بقاعدة البيانات لنفس النوافذ (آخر 7 أيام وآخر 30 يومًا).

يجيب عن: كم ملفًا وسطرًا ورسالة؟ كم رسالة تكررت أسطرها، وهل اختلفت أرقام المكرر (فيُفقد شيء بأخذ أولها)؟
وهل يطابق مجموع كل حقل (إدخال، قراءة سياق، حفظ سياق، مخرجات) وكل نموذج ما في قاعدة البيانات؟
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from neo.models import UsageTurn
from neo.services import usage

FIELDS = (("input_tokens", "input"), ("cache_read_input_tokens", "cache_read"),
          ("cache_creation_input_tokens", "cache_write"), ("output_tokens", "output"))


def _scan(roots) -> tuple[dict, dict]:
    stats = defaultdict(int)
    msgs: dict = {}  # key -> {"at", "model", "first": {...}, "max": {...}}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, names in os.walk(root):
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                stats["files"] += 1
                try:
                    f = open(os.path.join(dirpath, name), encoding="utf-8", errors="replace")  # noqa: SIM115
                except OSError:
                    stats["unreadable"] += 1
                    continue
                with f:
                    for line in f:
                        if '"usage"' not in line:
                            continue
                        try:
                            r = json.loads(line)
                        except ValueError:
                            stats["bad_json"] += 1
                            continue
                        m = r.get("message") or {}
                        u = m.get("usage")
                        if r.get("type") != "assistant" or not isinstance(u, dict):
                            continue
                        if m.get("model") in (None, "<synthetic>"):
                            stats["synthetic"] += 1
                            continue
                        stats["lines"] += 1
                        vals = {k: int(u.get(src) or 0) for src, k in FIELDS}
                        key = (m.get("id"), r.get("requestId")) if m.get("id") else (r.get("sessionId"), r.get("timestamp"),
                                                                                       tuple(vals.values()))
                        if key in msgs:
                            stats["dup_lines"] += 1
                            e = msgs[key]
                            if vals != e["first"]:
                                stats["dup_differ"] += 1
                            e["max"] = {k: max(e["max"][k], vals[k]) for k in vals}
                        else:
                            msgs[key] = {"at": r.get("timestamp"), "model": m["model"], "first": vals, "max": dict(vals)}
    return stats, msgs


def _window(msgs: dict, since, until, which: str) -> dict:
    tot, by_model = defaultdict(int), defaultdict(int)
    for e in msgs.values():
        try:
            day = timezone.localtime(datetime.fromisoformat(e["at"].replace("Z", "+00:00"))).date()
        except (AttributeError, ValueError):
            continue
        if since <= day <= until:
            v = e[which]
            for k in v:
                tot[k] += v[k]
            tot["turns"] += 1
            by_model[e["model"]] += v["output"]
    return {**tot, "by_model_output": dict(by_model)}


def _db(since, until) -> dict:
    qs = UsageTurn.objects.filter(day__range=(since, until))
    a = qs.aggregate(input=Sum("input_tokens"), cache_read=Sum("cache_read"), cache_write=Sum("cache_write"),
                     output=Sum("output_tokens"), turns=Count("pk"))
    by = dict(qs.values_list("model__name").annotate(o=Sum("output_tokens")))
    return {**{k: v or 0 for k, v in a.items()}, "by_model_output": by}


def verify(today=None) -> dict:
    today = today or timezone.localdate()
    roots = [str(d) for d in usage.dirs()]
    stats, msgs = _scan(roots)
    out = {"roots": [{"path": r, "found": os.path.isdir(r)} for r in roots], "checked_at": timezone.now().isoformat(),
           "files": stats["files"], "lines": stats["lines"], "messages": len(msgs), "dup_lines": stats["dup_lines"],
           "dup_differ": stats["dup_differ"], "synthetic": stats["synthetic"], "bad_json": stats["bad_json"],
           "windows": {}}
    ok = True
    for name, since in (("week", today - timedelta(days=6)), ("month", today - timedelta(days=29))):
        files, files_max, db = _window(msgs, since, today, "first"), _window(msgs, since, today, "max"), _db(since, today)
        diff = {k: db.get(k, 0) - files.get(k, 0) for k in ("input", "cache_read", "cache_write", "output", "turns")}
        models = sorted(set(files["by_model_output"]) | set(db["by_model_output"]))
        model_diff = {m: db["by_model_output"].get(m, 0) - files["by_model_output"].get(m, 0) for m in models}
        match = not any(diff.values()) and not any(model_diff.values())
        ok = ok and match
        out["windows"][name] = {
            "since": since.isoformat(), "files": {k: files.get(k, 0) for k in diff}, "db": {k: db[k] for k in diff},
            "diff": diff, "model_diff": {m: d for m, d in model_diff.items() if d}, "match": match,
            # لو أُخذ أكبر رقم بين أسطر الرسالة المكررة بدل أولها
            "output_if_max": files_max.get("output", 0) - files.get("output", 0)}
    out["ok"] = ok
    return out
