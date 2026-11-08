"""
python manage.py neo_backup            → نسخة احتياطية لقاعدة البيانات الآن (db-YYYYMMDD.sqlite3 في .local/backups)
الاسترجاع: أوقف الخادم والعامل ثم انسخ الملف المطلوب فوق backend/db.sqlite3.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from neo.services import backup_service


class Command(BaseCommand):
    help = "نسخة احتياطية لقاعدة البيانات (تُستبدل نسخة اليوم إن وُجدت)."

    def handle(self, *args, **opts):
        source = backup_service.db_file()
        if source is None:
            raise CommandError("لا ملف قاعدة بيانات حقيقي لنسخه.")
        path = backup_service.backup_db(source, settings.NEO_BACKUP_DIR, timezone.localdate())
        self.stdout.write(self.style.SUCCESS(f"نُسخت القاعدة: {path}"))
