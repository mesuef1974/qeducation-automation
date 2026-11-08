"""النسخ الاحتياطي، وحلقة العامل وإعادة تشغيله الذاتي، وأوامر الإدارة، والإعدادات الآمنة افتراضيًا."""
import importlib
import os
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.core.management import call_command, get_commands, load_command_class
from django.core.management.base import CommandError

from neo.management.commands import neo_worker
from neo.models import Job
from neo.services import backup_service
from neo.services.job_service import JobService, beat, stop_beat


def _make_db(path: Path, rows: int = 3) -> Path:
    con = sqlite3.connect(path)
    con.execute("create table t (v integer)")
    con.executemany("insert into t values (?)", [(i,) for i in range(rows)])
    con.commit()
    con.close()
    return path


def _count(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute("select count(*) from t").fetchone()[0]
    finally:
        con.close()


# ---- النسخ الاحتياطي ----

def test_backup_copies_data_and_leaves_source_untouched(tmp_path):
    src = _make_db(tmp_path / "src.sqlite3", rows=5)
    before = src.read_bytes()
    out = backup_service.backup_db(src, tmp_path / "b", date(2026, 11, 8))
    assert out.name == "db-20261108.sqlite3" and _count(out) == 5
    assert src.read_bytes() == before
    assert not list((tmp_path / "b").glob("*.tmp"))


def test_backup_keeps_only_latest(tmp_path):
    src = _make_db(tmp_path / "src.sqlite3")
    for i in range(6):
        backup_service.backup_db(src, tmp_path / "b", date(2026, 11, 1) + timedelta(days=i), keep=3)
    names = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert names == ["db-20261104.sqlite3", "db-20261105.sqlite3", "db-20261106.sqlite3"]


def test_backup_failure_leaves_no_partial_file(tmp_path):
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        backup_service.backup_db(bad, tmp_path / "b", date(2026, 11, 8))
    assert not list((tmp_path / "b").iterdir())


def test_run_if_due_once_per_day_and_never_raises(tmp_path, settings, monkeypatch):
    src = _make_db(tmp_path / "live.sqlite3")
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", src)
    settings.NEO_BACKUP_DIR = tmp_path / "b"
    day = date(2026, 11, 8)
    first = backup_service.run_if_due(day)
    assert first and first.exists()
    assert backup_service.run_if_due(day) is None  # نسخة اليوم موجودة
    # فشل النسخ يُسجَّل ولا يوقف العامل
    monkeypatch.setattr(backup_service, "backup_db", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    assert backup_service.run_if_due(day + timedelta(days=1)) is None


def test_no_backup_without_real_db_file(settings, tmp_path, monkeypatch):
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", ":memory:")
    settings.NEO_BACKUP_DIR = tmp_path / "b"
    assert backup_service.run_if_due(date(2026, 11, 8)) is None and not (tmp_path / "b").exists()


def test_neo_backup_command(tmp_path, settings, monkeypatch):
    src = _make_db(tmp_path / "live.sqlite3", rows=2)
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", src)
    settings.NEO_BACKUP_DIR = tmp_path / "b"
    call_command("neo_backup")
    (only,) = (tmp_path / "b").glob("db-*.sqlite3")
    assert _count(only) == 2
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", ":memory:")
    with pytest.raises(CommandError):
        call_command("neo_backup")


# ---- العامل ----

@pytest.fixture
def quiet_worker(monkeypatch):
    """العامل بلا ترحيل ولا قتل متصفحات حقيقية ولا نسخ احتياطي."""
    monkeypatch.setattr(neo_worker, "call_command", lambda *a, **k: None)
    monkeypatch.setattr(neo_worker, "kill_orphan_browsers", lambda: 0)
    monkeypatch.setattr(neo_worker.backup_service, "run_if_due", lambda day: None)
    monkeypatch.delenv("NEO_WORKER_RESTART", raising=False)


def test_worker_refuses_second_instance(db, quiet_worker):
    beat(os.getpid())
    try:
        with pytest.raises(CommandError, match="عامل آخر"):
            call_command("neo_worker", "--once")
    finally:
        stop_beat()


def test_worker_once_runs_queued_job_then_exits(db, quiet_worker, monkeypatch, capsys):
    job, _ = JobService().enqueue(Job.Kind.SESSION)
    ran = []

    def fake_run(self, j, *a, **k):
        ran.append(j.pk)
        j.status = Job.Status.DONE
        j.save(update_fields=["status"])
        return j

    monkeypatch.setattr(JobService, "run", fake_run)
    call_command("neo_worker", "--once")
    assert ran == [job.pk]
    out = capsys.readouterr().out
    assert f"[#{job.pk}]" in out
    assert not Job.objects.filter(status=Job.Status.RUNNING).exists()


def test_worker_recovers_stale_running_job_on_start(db, quiet_worker):
    stale = Job.objects.create(kind=Job.Kind.SESSION, key="stale", status=Job.Status.RUNNING)
    call_command("neo_worker", "--once")
    stale.refresh_from_db()
    assert stale.status == Job.Status.FAILED and "توقف العامل" in stale.error


def test_code_change_detection(tmp_path, monkeypatch):
    f = tmp_path / "m.py"
    f.write_text("x = 1", encoding="utf-8")
    monkeypatch.setattr(neo_worker.autoreload, "iter_all_python_module_files", lambda: [f])
    snap = neo_worker._code_snapshot()
    assert not neo_worker._code_changed(snap)
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert neo_worker._code_changed(snap)


def test_tree_state_sees_new_files_and_skips_ignored_dirs(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / ".neo_profile").mkdir()
    (tmp_path / ".neo_profile" / "skip.py").write_text("", encoding="utf-8")
    before = neo_worker._tree_state()
    assert [Path(p).name for p in before] == ["a.py"]
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    assert len(neo_worker._tree_state()) == 2


def test_wait_settled_returns_after_quiet_period(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    start = time.monotonic()
    neo_worker._wait_settled(settle_s=1, limit_s=10)
    assert 1 <= time.monotonic() - start < 5


def test_wait_settled_is_bounded(tmp_path, settings, monkeypatch):
    settings.BASE_DIR = tmp_path
    n = iter(range(10_000))
    monkeypatch.setattr(neo_worker, "_tree_state", lambda: {"p": next(n)})  # يتغيّر دائمًا
    real_sleep = time.sleep
    monkeypatch.setattr(neo_worker.time, "sleep", lambda s: real_sleep(0.01))
    start = time.monotonic()
    neo_worker._wait_settled(settle_s=5, limit_s=0.3)
    assert time.monotonic() - start < 2


# ---- أوامر الإدارة ----

def test_every_neo_command_builds_its_parser():
    names = [n for n, app in get_commands().items() if app == "neo"]
    assert {"neo_worker", "neo_sync", "neo_backup", "neo_login"} <= set(names)
    for name in names:
        load_command_class("neo", name).create_parser("manage.py", name)


# ---- الإعدادات الآمنة افتراضيًا ----

def test_debug_off_by_default(monkeypatch):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    monkeypatch.delenv("NEO_HTTPS", raising=False)
    fresh = importlib.reload(importlib.import_module("config.settings"))
    try:
        assert fresh.DEBUG is False and fresh.SESSION_COOKIE_SECURE is False
        assert fresh.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] == ["rest_framework.renderers.JSONRenderer"]
    finally:
        importlib.reload(fresh)


def test_admin_static_served_with_debug_off(db, client, settings):
    settings.DEBUG = False
    assert client.get("/static/admin/css/base.css").status_code == 200
