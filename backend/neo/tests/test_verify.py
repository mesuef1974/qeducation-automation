from datetime import date
from pathlib import Path

from neo.domain.types import ParsedLesson
from neo.infrastructure.parsers import parse_student_lessons
from neo.models import PlatformLesson, SyncRun
from neo.services.sync_service import SyncService
from neo.services.verify_service import VerifyService, compare

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 2)


def test_parse_student_lessons():
    tiles, today = parse_student_lessons((FIX / "student_lessons.html").read_text(encoding="utf-8"))
    assert tiles == {16646488, 17844978} and today == {17844979}


def lessons(klass):
    SyncService().ingest(klass, [
        ParsedLesson(1, 1, "ماضٍ يراه", "", date(2026, 10, 1), 1),
        ParsedLesson(2, 2, "ماضٍ لا يراه", "", date(2026, 11, 1), 3),
        ParsedLesson(3, 3, "اليوم في اللوحة", "", TODAY, 6),
        ParsedLesson(4, 4, "مستقبلي", "", date(2026, 11, 4), 6),
        ParsedLesson(5, 5, "مخفي يراه", "", date(2026, 11, 5), 1, hidden=True),
        ParsedLesson(6, 6, "بلا تاريخ", "", None, None),
    ], [])
    return list(PlatformLesson.objects.filter(klass=klass))


def test_compare(classes):
    r = compare(lessons(classes[602598]), tiles={1, 5}, today_ids={3}, today=TODAY)
    assert (r.missing, r.today_missing, r.unexpected, r.scheduled, r.undated) == ([2], [], [5], [4], [6])
    assert not r.ok
    r = compare(lessons(classes[602598]), tiles={1, 2}, today_ids=set(), today=TODAY)
    assert r.today_missing == [3] and not r.ok


def test_record(classes):
    k = classes[602598]
    lessons(k)
    run = VerifyService().record(k, {1, 2}, {3}, TODAY)
    assert run.kind == SyncRun.Kind.VERIFY and run.ok
    assert run.summary["scheduled_future"] == 1 and run.summary["hidden_but_seen"] == []
