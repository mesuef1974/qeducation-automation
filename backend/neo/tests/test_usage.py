import json
from datetime import date

import pytest

from neo.models import UsageModel, UsageSession, UsageTool, UsageTurn, UsageTurnTool
from neo.services import usage


def _line(at, model="claude-opus-5-5", cr=1000, cw=100, out=10, inp=5, tools=(), mid="m1", sid="s1"):
    return json.dumps({"type": "assistant", "timestamp": at, "sessionId": sid, "requestId": "r" + mid,
                       "message": {"id": mid, "model": model, "content": [{"type": "tool_use", "name": n} for n in tools],
                                   "usage": {"input_tokens": inp, "cache_read_input_tokens": cr,
                                             "cache_creation_input_tokens": cw, "output_tokens": out}}})


@pytest.fixture
def logs(tmp_path, settings):
    settings.NEO_USAGE_DIRS = [tmp_path]
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "s1.jsonl").write_text("\n".join([
        _line("2026-11-04T10:00:00Z", tools=["Bash"], mid="a"),
        _line("2026-11-04T10:00:00Z", tools=["Bash"], mid="a"),  # الرسالة نفسها مكررة
        _line("2026-11-02T10:00:00Z", model="claude-sonnet-5-5", out=1, mid="b"),
        _line("2026-10-20T10:00:00Z", mid="c"),
        json.dumps({"type": "user", "message": {"content": "نص لا يُقرأ"}}),
    ]) + "\n", encoding="utf-8")
    return proj / "s1.jsonl"


@pytest.mark.django_db
def test_import_and_periods(logs):
    assert usage.import_all() == {"files": 1, "new": 3, "pending": False}
    assert usage.import_all()["new"] == 0  # لم يتغيّر الملف: لا يُقرأ
    assert [t.name for t in UsageTool.objects.all()] == ["Bash"] and UsageTurnTool.objects.get().uses == 1
    assert UsageSession.objects.get().project.name == "proj" and UsageModel.objects.count() == 2
    today = date(2026, 11, 4)
    one = 5 + 0.1 * 1000 + 2 * 100 + 5 * 10
    d = usage.build(today=today, since=today)
    t = d["totals"]
    assert (t["effective"], t["tokens"], t["turns"], t["sessions"]) == (round(one), 1115, 1, 1)
    g = {x["name"]: x["effective"] for x in d["groups"]}
    assert g[usage.CONTEXT_READ] == 105 and g["العمل على الملفات والأوامر"] == 50
    d = usage.build(today=today)  # افتراضه آخر 30 يومًا، ولا يبدأ قبل أول يوم في البيانات
    assert d["filter"]["since"] == date(2026, 10, 20) and len(d["daily"]) == 16 and d["daily"][-1]["turns"] == 1
    assert d["panel"]["week"]["all"]["turns"] == 2 and d["panel"]["month"]["all"]["turns"] == 3
    assert d["panel"]["week"]["fable"]["turns"] == 0 and d["session_total"]["turns"] == 3
    assert [m["model"] for m in d["models"]] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert [f["family"] for f in d["families"]] == ["Opus", "Sonnet", "Fable"]  # Fable ظاهر ولو صفرًا
    assert [m["model"] for m in d["all_models"]] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    only = usage.build(today=today, models=["claude-sonnet-5-5"])
    assert only["totals"]["turns"] == 1 and only["panel"]["week"]["all"]["turns"] == 2  # اللوحة لا يمسها المرشّح
    m = {x["month"]: x for x in d["monthly"]}
    assert list(m) == ["2026-10", "2026-11"] and m["2026-10"]["partial"] and m["2026-10"]["days"] == 12
    assert m["2026-11"]["turns"] == 2 and m["2026-11"]["days"] == 4 and m["2026-11"]["per_day"] == m["2026-11"]["tokens"] // 4


@pytest.mark.django_db
def test_incremental_append_and_partial_line(logs):
    usage.import_all()
    with logs.open("a", encoding="utf-8") as f:
        f.write(_line("2026-11-04T11:00:00Z", mid="d") + "\n" + _line("2026-11-04T12:00:00Z", mid="e")[:40])
    assert usage.import_all()["new"] == 1  # السطر الناقص ينتظر اكتماله
    with logs.open("a", encoding="utf-8") as f:
        f.write(_line("2026-11-04T12:00:00Z", mid="e")[40:] + "\n")
    assert usage.import_all()["new"] == 1 and UsageTurn.objects.count() == 5


@pytest.mark.django_db
def test_api(client, logs):
    assert client.get("/api/neo/usage/").json()["imported"] is None  # القراءة لا تستورد
    r = client.post("/api/neo/usage/?days=all").json()
    assert r["imported"]["new"] == 3 and r["totals"]["turns"] == 3 and r["session_total"]["turns"] == 3
    r = client.get("/api/neo/usage/?from=2026-11-02&to=2026-11-04&models=claude-sonnet-5-5").json()
    assert r["filter"]["days"] == 3 and r["filter"]["models"] == ["claude-sonnet-5-5"]
    assert client.get("/api/neo/usage/?days=abc").status_code == 400


@pytest.mark.django_db
def test_budget_resumes(logs, monkeypatch):
    monkeypatch.setattr(usage, "BATCH", 1)
    r = usage.import_all(budget_s=0)  # المهلة انتهت بعد أول دفعة: يُستأنف
    assert r["pending"] and UsageTurn.objects.count() == 1
    while usage.import_all(budget_s=0)["pending"]:
        pass
    assert UsageTurn.objects.count() == 3


def test_export_strips_text(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ex", Path(__file__).resolve().parents[3] / "tools" / "export_usage.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    src = tmp_path / "s.jsonl"
    rec = json.loads(_line("2026-11-04T10:00:00Z", tools=["Bash"]))
    rec["message"]["content"].append({"type": "text", "text": "سر"})
    src.write_text(json.dumps(rec) + "\n" + json.dumps({"type": "user", "message": {"content": "سر"}}), encoding="utf-8")
    out = ex.main(src, tmp_path / "out").read_text(encoding="utf-8")
    assert "سر" not in out and '"Bash"' in out and out.count("\n") == 1


@pytest.mark.django_db
def test_verify_matches_db(logs):
    from neo.services import usage_verify
    usage.import_all(budget_s=None)
    r = usage_verify.verify(today=date(2026, 11, 4))
    assert r["ok"] and r["files"] == 1 and r["lines"] == 4 and r["messages"] == 3 and r["dup_lines"] == 1
    assert r["dup_differ"] == 0 and r["windows"]["week"]["files"]["turns"] == 2
    UsageTurn.objects.filter(model__name="claude-sonnet-5-5").update(output_tokens=999)  # قاعدة لا تطابق الملفات
    bad = usage_verify.verify(today=date(2026, 11, 4))
    assert not bad["ok"] and bad["windows"]["week"]["diff"]["output"] == 998
    assert bad["windows"]["week"]["model_diff"] == {"claude-sonnet-5-5": 998}


@pytest.mark.django_db
def test_verify_job(logs):
    from neo.models import Job
    from neo.services.job_service import JobService
    job, _ = JobService().enqueue(Job.Kind.USAGE_VERIFY)
    job = JobService().run(JobService().claim())
    assert job.status == Job.Status.DONE and job.report["ok"] and UsageTurn.objects.count() == 3


@pytest.mark.django_db
def test_duplicate_lines_take_max(logs):
    """أول سطر للرسالة قد يحمل رقم مخرجات مؤقتًا: يُحفظ الأكبر، ولو جاء السطر الأكبر في استيراد لاحق."""
    from neo.services import usage_verify
    usage.import_all(budget_s=None)
    with logs.open("a", encoding="utf-8") as f:
        f.write(_line("2026-11-04T10:00:00Z", tools=["Bash"], out=40, mid="a") + "\n")
    usage.import_all(budget_s=None)
    assert UsageTurn.objects.get(key__startswith="a:").output_tokens == 40 and UsageTurn.objects.count() == 3
    r = usage_verify.verify(today=date(2026, 11, 4))
    assert r["ok"] and r["dup_differ"] == 1 and r["windows"]["week"]["output_first_line_loss"] == 30
