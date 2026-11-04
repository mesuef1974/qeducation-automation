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
    d = usage.build(today=date(2026, 11, 4))
    one = 5 + 0.1 * 1000 + 2 * 100 + 5 * 10
    t = d["totals"]["today"]
    assert (t["effective"], t["tokens"], t["turns"], t["sessions"]) == (round(one), 1115, 1, 1)
    assert d["totals"]["week"]["turns"] == 2 and d["totals"]["month"]["turns"] == 2 and d["totals"]["session"]["turns"] == 3
    assert [m["model"] for m in d["models"]["week"]] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    g = {x["name"]: x["effective"] for x in d["groups"]["today"]}
    assert g[usage.CONTEXT_READ] == 105 and g["العمل على الملفات والأوامر"] == 50
    assert len(d["daily"]) == 30 and d["daily"][-1]["day"] == date(2026, 11, 4) and d["daily"][-1]["turns"] == 1
    assert d["sessions"][0]["project"] == "proj" and d["sessions"][0]["turns"] == 3


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
    r = client.post("/api/neo/usage/").json()
    assert r["imported"]["new"] == 3 and r["totals"]["session"]["turns"] == 3 and r["projects"][0]["project"] == "proj"


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
