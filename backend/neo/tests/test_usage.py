import json
from datetime import UTC, date, datetime, timedelta

import pytest

from neo.services import usage

MODELS = ["Sonnet 5.5", "Fable 5.1", "أخرى (أقدم)"]
COLS = ["d", "m", "g", "t", "i", "cc", "cr", "u", "v"]


def _page(rows):
    main = {"models": MODELS, "first_day": "2026-10-20", "last_day": "2026-11-04", "plan_label": "Ultra",
            "a": {"$cols": COLS, "rows": rows}}
    return f'<html><script type="application/json" id="data-main">{json.dumps(main)}</script></html>'


@pytest.fixture
def mizan(monkeypatch):
    now = datetime.now(UTC)
    reset = (now + timedelta(days=3)).isoformat().replace("+00:00", "Z")
    plan = [
        {"ts": (now - timedelta(hours=20)).isoformat().replace("+00:00", "Z"), "f": None, "fr": None, "w": 4, "wr": reset,
         "fa": 1, "far": reset, "pl": None, "src": "cli_usage"},
        {"ts": now.isoformat().replace("+00:00", "Z"), "f": 12, "fr": reset, "w": 6, "wr": reset, "fa": 2, "far": reset,
         "pl": None, "src": "cli_usage"},
    ]
    rows = [["2026-11-04", 0, "human", 10, 1, 100, 1000, 9, 0], ["2026-11-04", 1, "sub", 5, 2, 200, 2000, 8, 0],
            ["2026-11-02", 0, "scheduled", 3, 0, 10, 100, 1, 0], ["2026-10-20", 2, "unknown", 1, 0, 0, 50, 0, 0]]
    pages = {"/": _page(rows), "/plan.json": json.dumps(plan)}
    calls = []
    monkeypatch.setattr(usage, "_get", lambda path: calls.append(path) or pages[path])
    usage._cache.update(at=0.0, data=None)
    return calls


def test_build_from_mizan(mizan):
    today = date(2026, 11, 4)
    d = usage.build(today=today)
    assert d["source"]["name"] == "ميزان" and d["source"]["plan"] == "Ultra"
    assert d["filter"]["since"] == date(2026, 10, 20) and len(d["daily"]) == 16  # لا يبدأ قبل أول يوم في «ميزان»
    assert d["totals"]["turns"] == 19 and d["totals"]["tokens"] == 1110 + 2210 + 111 + 50
    assert [m["model"] for m in d["models"]] == ["Fable 5.1", "Sonnet 5.5", "أخرى (أقدم)"]
    assert {o["label"] for o in d["origins"]} == {"إنسان", "وكيل فرعي", "مجدول", "بلا أصل مسجّل"}
    m = {x["month"]: x for x in d["monthly"]}
    assert m["2026-10"]["partial"] and m["2026-10"]["days"] == 12 and m["2026-11"]["tokens"] == 1110 + 2210 + 111


def test_quota_and_filters(mizan):
    d = usage.build(today=date(2026, 11, 4), models=["Sonnet 5.5"])
    assert d["totals"]["turns"] == 13 and d["panel"]["month"]["all"]["turns"] == 19  # اللوحة لا يمسها المرشّح
    w, fa, f5 = d["quota"]["week"], d["quota"]["fable"], d["quota"]["five_hour"]
    assert w["pct"] == 6 and w["source"] == "cli_usage" and not w["stale"] and fa["pct"] == 2 and f5["pct"] == 12
    assert set(w) == {"pct", "reset", "at", "source", "stale"}  # كما في «ميزان» بلا تقدير


def test_cache_and_unavailable(mizan, monkeypatch):
    usage.build(today=date(2026, 11, 4))
    usage.build(today=date(2026, 11, 4))
    assert mizan.count("/") == 1  # المخزّن دقيقة
    usage.build(today=date(2026, 11, 4), force=True)
    assert mizan.count("/") == 2

    def down(path):
        raise usage.MizanUnavailable("تعذّر الوصول إلى «ميزان»")
    monkeypatch.setattr(usage, "_get", down)
    usage._cache.update(at=0.0, data=None)
    with pytest.raises(usage.MizanUnavailable):
        usage.build()


@pytest.mark.django_db
def test_api(client, mizan, monkeypatch):
    r = client.get("/api/neo/usage/?from=2026-11-02&to=2026-11-04&models=Sonnet 5.5")
    assert r.status_code == 200 and r.json()["filter"]["days"] == 3
    assert client.get("/api/neo/usage/?days=abc").status_code == 400
    monkeypatch.setattr(usage, "fetch", lambda force=False: (_ for _ in ()).throw(usage.MizanUnavailable("لا يعمل")))
    r = client.get("/api/neo/usage/")
    assert r.status_code == 503 and "لا يعمل" in r.json()["detail"]
