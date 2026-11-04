from django.core.management.base import BaseCommand

from neo.services import usage


class Command(BaseCommand):
    help = "يستورد استهلاك جلسات Claude من مجلداتها (NEO_USAGE_DIRS) إلى قاعدة البيانات ويطبع الملخص"

    def handle(self, *args, **opts):
        r = usage.import_all()
        self.stdout.write(f"الملفات {r['files']} · خطوات جديدة {r['new']}")
        d = usage.build()
        for k, label in (("session", "الجلسة الأخيرة"), ("today", "اليوم"), ("week", "الأسبوع"), ("month", "الشهر")):
            t = d["totals"][k]
            self.stdout.write(f"{label}: {t['effective']:,} وحدة فعلية · {t['tokens']:,} رمز · {t['turns']} خطوة")
        for m in d["models"]["month"]:
            self.stdout.write(f"  {m['model']}: {m['effective']:,}")
