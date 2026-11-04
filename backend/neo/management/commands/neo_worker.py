"""
python manage.py neo_worker          → العامل: ينفّذ مهام الواجهة واحدة تلو الأخرى (Ctrl+C للإيقاف)
python manage.py neo_worker --once   → ينفّذ المهام المنتظرة الآن ثم يخرج
يعيد تشغيل نفسه عند تغيّر الكود وهو خامل بين المهام فقط (لا يقطع مهمة على المنصة) ما لم يُمرَّر --noreload،
وينظّف عند بدئه متصفحًا يتيمًا يقفل ملف الدخول.
"""
import os
import sys
import threading
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection
from django.utils import autoreload, timezone

from neo.infrastructure.client import kill_orphan_browsers
from neo.models import Job
from neo.services import weekly_service
from neo.services.job_service import HEARTBEAT_S, JobService, beat, stop_beat, worker_alive

SCHEDULE_CHECK_S = 60
CODE_CHECK_S = 5
SETTLE_S = 10  # إعادة التشغيل بعد ثبات الكود: النسخ (git) يستغرق ثواني، فلا يبدأ العامل على كود نصف منسوخ
SKIP_DIRS = {".neo_profile", "media", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def _code_snapshot() -> dict:
    return {f: f.stat().st_mtime for f in autoreload.iter_all_python_module_files() if f.exists()}


def _code_changed(snapshot: dict) -> bool:
    """تغيّر ملف كان محمّلًا عند البدء؛ الملفات التي تُستورد لاحقًا لا تُحسب تغييرًا."""
    current = _code_snapshot()
    return any(current.get(f, m) != m for f, m in snapshot.items())


def _tree_state() -> dict:
    """mtime لكل ملف .py في المشروع، ومنها الملفات الجديدة التي لم تُحمَّل بعد."""
    out = {}
    for root, dirs, files in os.walk(settings.BASE_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    out[path] = os.stat(path).st_mtime
                except OSError:
                    pass
    return out


def _wait_settled(settle_s: float = SETTLE_S, limit_s: float = 120) -> None:
    """ينتظر حتى لا يتغيّر أي ملف كود خلال settle_s ثانية (بحد أقصى limit_s)."""
    last, since, deadline = _tree_state(), time.monotonic(), time.monotonic() + limit_s
    while time.monotonic() < deadline and time.monotonic() - since < settle_s:
        time.sleep(1)
        current = _tree_state()
        if current != last:
            last, since = current, time.monotonic()


def _pulse(stop: threading.Event) -> None:
    """نبض في خيط مستقل، فيستمر أثناء مهمة طويلة على المنصة."""
    pid = os.getpid()
    while not stop.wait(HEARTBEAT_S):
        try:
            beat(pid)
        except OperationalError:  # قفل SQLite عابر: نبضة تفوت ولا يموت الخيط
            connection.close()
    connection.close()


class Command(BaseCommand):
    help = "عامل مهام الواجهة: ينفّذ المهام على المنصة بالترتيب، مهمة واحدة في كل مرة."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0, help="ثوانٍ بين فحص الطابور")
        parser.add_argument("--noreload", action="store_true", help="بلا إعادة تحميل عند تغيّر الكود")

    def handle(self, *args, once, interval, noreload, **opts):
        if worker_alive() and not os.environ.get("NEO_WORKER_RESTART"):  # عاملان معًا يتنازعان المتصفح والمهام
            raise CommandError("عامل آخر يعمل الآن (نبضه حديث). أوقفه أولًا.")
        os.environ.pop("NEO_WORKER_RESTART", None)
        # قاعدة البيانات محدّثة قبل أي مهمة، ومنها إعادة التشغيل الذاتية بعد تغيّر الكود (start.ps1 يرحّل عند البدء فقط)
        call_command("migrate", interactive=False, verbosity=0)
        svc = JobService()
        if n := svc.recover():
            self.stdout.write(self.style.WARNING(f"عُلّمت {n} مهمة متوقفة بالفشل."))
        if k := kill_orphan_browsers():
            self.stdout.write(self.style.WARNING(f"أُنهي {k} متصفحًا يتيمًا كان يقفل ملف الدخول."))
        self.stdout.write("العامل يعمل. (Ctrl+C للإيقاف)" if not once else "تنفيذ المهام المنتظرة...")
        beat(os.getpid())
        stop = threading.Event()
        threading.Thread(target=_pulse, args=(stop,), daemon=True).start()
        checked, code_checked = 0.0, time.monotonic()
        snapshot = {} if once or noreload else _code_snapshot()
        try:
            while True:
                if snapshot and time.monotonic() - code_checked >= CODE_CHECK_S:  # الكود تغيّر؟ ونحن خاملون هنا
                    code_checked = time.monotonic()
                    if _code_changed(snapshot) and not Job.objects.filter(status=Job.Status.RUNNING).exists():
                        self.stdout.write("تغيّر الكود؛ يُعاد تشغيل العامل بعد ثبات الملفات.")
                        _wait_settled()
                        stop.set()
                        stop_beat()
                        connection.close()
                        os.environ["NEO_WORKER_RESTART"] = "1"  # النبض الأخير نبضنا، لا عامل آخر
                        os.execv(sys.executable, [sys.executable, *sys.argv])
                if time.monotonic() - checked >= SCHEDULE_CHECK_S:  # الدورة الأسبوعية حين يحين موعدها
                    checked = time.monotonic()
                    if due := weekly_service.enqueue_due(timezone.localtime(), svc.enqueue):
                        self.stdout.write(f"[#{due.pk}] حان موعد الدورة الأسبوعية {due.params['cycle']}")
                job = svc.claim()
                if job is None:
                    if once:
                        return
                    time.sleep(interval)
                    continue
                self.stdout.write(f"[#{job.pk}] {job.get_kind_display()} {job.params or ''}")
                job = svc.run(job)
                write = self.style.SUCCESS if job.status == job.Status.DONE else self.style.ERROR
                self.stdout.write(write(f"[#{job.pk}] {job.get_status_display()}"
                                        f"{': ' + job.error if job.error else ''}"))
        except KeyboardInterrupt:
            self.stdout.write("أُوقف العامل.")
        finally:
            stop.set()
            stop_beat()
