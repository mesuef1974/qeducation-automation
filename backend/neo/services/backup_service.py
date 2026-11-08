"""
نسخ احتياطي يومي لقاعدة البيانات (db.sqlite3): المصدر الوحيد للاعتماد والمهام وسجل العمليات.
بواجهة النسخ في sqlite نفسها (آمنة والعامل يكتب)، تُكتب في ملف مؤقت ثم تُسمّى، ولا يُحتفظ إلا بآخر KEEP نسخة.
المجلد خارج git (.local/backups) وعلى الجهاز وحده (PDPPL).
"""
import logging
import sqlite3
from datetime import date
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

KEEP = 14
PREFIX = "db-"
SUFFIX = ".sqlite3"


def _name(day: date) -> str:
    return f"{PREFIX}{day:%Y%m%d}{SUFFIX}"


def backup_db(source: Path, dest_dir: Path, day: date, keep: int = KEEP) -> Path:
    """ينسخ source إلى dest_dir/db-YYYYMMDD.sqlite3 ويتحقق من سلامة النسخة، ثم يقلّم القديم."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / _name(day)
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)  # قراءة فقط: لا نلمس الأصل
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("فشل فحص سلامة النسخة الاحتياطية")
    except Exception:
        dst.close()
        src.close()
        tmp.unlink(missing_ok=True)
        raise
    dst.close()
    src.close()
    tmp.replace(target)
    for old in sorted(dest_dir.glob(f"{PREFIX}*{SUFFIX}"))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def db_file() -> Path | None:
    name = settings.DATABASES["default"]["NAME"]
    path = Path(str(name))
    return path if path.is_file() else None  # بلا ملف حقيقي (ذاكرة/اختبار): لا شيء يُنسخ


def due(day: date, dest_dir: Path | None = None) -> bool:
    return not ((dest_dir or settings.NEO_BACKUP_DIR) / _name(day)).exists()


def run_if_due(day: date) -> Path | None:
    """نسخة اليوم إن لم تُؤخذ بعد. لا يرفع استثناءً: فشل النسخ يُسجَّل ولا يوقف العامل."""
    source = db_file()
    if source is None or not due(day):
        return None
    try:
        path = backup_db(source, settings.NEO_BACKUP_DIR, day)
    except (OSError, sqlite3.Error):
        log.exception("تعذّر النسخ الاحتياطي لقاعدة البيانات")
        return None
    log.info("نسخة احتياطية: %s", path.name)
    return path
