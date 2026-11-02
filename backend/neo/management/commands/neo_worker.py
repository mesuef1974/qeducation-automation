"""
python manage.py neo_worker          → العامل: ينفّذ مهام الواجهة واحدة تلو الأخرى (Ctrl+C للإيقاف)
python manage.py neo_worker --once   → ينفّذ المهام المنتظرة الآن ثم يخرج
"""
import os
import threading
import time

from django.core.management.base import BaseCommand
from django.db import connection

from neo.services.job_service import HEARTBEAT_S, JobService, beat, stop_beat


def _pulse(stop: threading.Event) -> None:
    """نبض في خيط مستقل، فيستمر أثناء مهمة طويلة على المنصة."""
    pid = os.getpid()
    while not stop.wait(HEARTBEAT_S):
        beat(pid)
    connection.close()


class Command(BaseCommand):
    help = "عامل مهام الواجهة: ينفّذ المهام على المنصة بالترتيب، مهمة واحدة في كل مرة."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0, help="ثوانٍ بين فحص الطابور")

    def handle(self, *args, once, interval, **opts):
        svc = JobService()
        if n := svc.recover():
            self.stdout.write(self.style.WARNING(f"عُلّمت {n} مهمة متوقفة بالفشل."))
        self.stdout.write("العامل يعمل. (Ctrl+C للإيقاف)" if not once else "تنفيذ المهام المنتظرة...")
        beat(os.getpid())
        stop = threading.Event()
        threading.Thread(target=_pulse, args=(stop,), daemon=True).start()
        try:
            while True:
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
