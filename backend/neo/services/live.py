"""
البث الحي لعمل العامل (تبويب «مباشر»).

كل مهمة تكتب أحداثها سطرًا سطرًا في ملف JSON Lines (media/live/job_<id>.jsonl)، بلا ORM، فيصلح من داخل سياق
Playwright ومن أي خيط، ولا يزاحم قاعدة البيانات. الخادم يقرأ الملف ويعيد ما بعد آخر رقم تسلسلي رآه المتصفح.
خارج المهام (أوامر الطرفية) لا يُكتب شيء. أي خطأ في البث يُتجاهل: البث لا يوقف العمل أبدًا.

الحدث: seq، at (UTC)، t (ثوانٍ منذ بدء المهمة)، kind، text، stage، node، وحسب النوع current/total أو status/ms.
الأنواع: start | stage | step | net | file | warn | error | end
node: عقدة رسم الأتمتة التي يجري فيها الحدث (NODES)، تُضبط مع المرحلة فيتحرك الرسم في «مباشر» مع العمل.
"""
import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

KEEP = 300  # ملفات آخر المهام المحفوظة
NODES = ("platform", "fetch", "audit", "plan", "approve", "apply", "verify", "scorecard", "prep")
_lock = threading.Lock()
_state: dict = {"path": None, "seq": 0, "t0": 0.0, "stage": "", "node": ""}


def live_dir() -> Path:
    return Path(getattr(settings, "NEO_LIVE_DIR", Path(settings.MEDIA_ROOT) / "live"))


def job_path(job_id: int) -> Path:
    return live_dir() / f"job_{job_id}.jsonl"


def active() -> bool:
    return _state["path"] is not None


def start(job_id: int, title: str) -> None:
    try:
        live_dir().mkdir(parents=True, exist_ok=True)
        _prune()
        with _lock:
            _state.update(path=job_path(job_id), seq=0, t0=time.monotonic(), stage="", node="")
            _state["path"].write_text("", encoding="utf-8")
    except OSError:
        _state["path"] = None
        return
    emit("start", title)


def emit(kind: str, text: str, node: str | None = None, **extra) -> None:
    """node يغيّر عقدة الرسم الحالية من هذا الحدث فصاعدًا (حتى المرحلة التالية)."""
    if _state["path"] is None:
        return
    with _lock:
        path = _state["path"]
        if path is None:
            return
        _state["seq"] += 1
        if kind == "stage":
            _state["stage"] = text
        if node in NODES:
            _state["node"] = node
        ev = {"seq": _state["seq"], "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
              "t": round(time.monotonic() - _state["t0"], 2), "kind": kind, "text": text, "stage": _state["stage"]}
        if _state["node"]:
            ev["node"] = _state["node"]
        ev.update({k: v for k, v in extra.items() if v is not None})
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError:
            pass


def stage(text: str, node: str | None = None) -> None:
    emit("stage", text, node=node)


def step(text: str, current: int | None = None, total: int | None = None, **extra) -> None:
    emit("step", text, current=current, total=total, **extra)


def end(status: str, text: str) -> None:
    emit("end", text, status=status)
    with _lock:
        _state["path"] = None


def read(job_id: int, since: int = 0, limit: int = 400) -> list[dict]:
    """أحداث المهمة بعد since. السطر الذي لم يكتمل بعد يُترك للقراءة التالية."""
    path = job_path(job_id)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("seq", 0) > since:
            out.append(ev)
    return out[-limit:]


def _prune() -> None:
    files = sorted(live_dir().glob("job_*.jsonl"), key=lambda p: p.stat().st_mtime)
    for p in files[:-KEEP]:
        try:
            p.unlink()
        except OSError:
            pass


# ------------------------------------------------------------- تسمية صفحات المنصة

_PAGES = (
    (r"^/files/", "ملف"),
    (r"^/teacher_lessons/list/", "قائمة الدروس"),
    (r"^/class_configure/schedule/", "الجدول الدراسي"),
    (r"^/teacher_lesson/notes/", "ملاحظات المعلم"),
    (r"^/teacher_lesson/show/.*section_id=", "قسم في الدرس"),
    (r"^/teacher_lesson/show_competencies/", "نتاجات الدرس"),
    (r"^/teacher_lesson/edit_competencies/", "نموذج ربط النتاجات"),
    (r"^/teacher_lesson/show/", "صفحة الدرس"),
    (r"^/teacher_lesson/edit/", "نموذج الدرس"),
    (r"^/teacher_lesson/shown/", "رؤية الدرس"),
    (r"^/teacher_lesson/set_shown_default/", "إظهار الدرس"),
    (r"^/teacher_lesson/completion/", "متطلبات الإنجاز"),
    (r"^/teacher_lesson/new_rule_action/", "نموذج منح النقاط"),
    (r"^/teacher_assignments/", "التقييمات"),
    (r"^/teacher_quiz_assignment/", "تقييم"),
    (r"^/quiz_question_bank/", "بنك الأسئلة"),
    (r"^/teacher_html_section/", "قسم صفحة"),
    (r"^/student_lessons/|^/teacher_class/submit_view_as", "عرض الطالب"),
    (r"^/student_class/view_as_teacher/", "العودة إلى عرض المعلم"),
    (r"^/user_dashboard", "الصفحة الرئيسية"),
)


def page_label(path: str) -> str:
    """«/teacher_lesson/notes/602728?lesson_id=…» ← «ملاحظات المعلم»؛ ما لا يُعرف يُعرض مساره."""
    path = re.sub(r"^https?://[^/]+", "", path)
    return next((label for pattern, label in _PAGES if re.search(pattern, path)), path.split("?")[0])


def summary(job_id: int) -> dict:
    """ملخص المهمة من كل أحداثها: عدّاد كل نوع، والمراحل بترتيبها وزمن بدئها وعقدتها، والعقد التي مرّت بها
    المهمة بترتيبها، وآخر تقدّم، والنهاية."""
    events = read(job_id, 0, limit=100_000)
    counts: dict[str, int] = {}
    ops: dict[str, int] = {}  # عمليات الملفات: download | cache | edit
    stages: list[dict] = []
    nodes: list[str] = []
    progress, ended = None, None
    for ev in events:
        counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1
        if ev.get("node") and (not nodes or nodes[-1] != ev["node"]):
            nodes.append(ev["node"])
        if ev.get("op"):
            ops[ev["op"]] = ops.get(ev["op"], 0) + 1
        if ev["kind"] == "stage":
            stages.append({"text": ev["text"], "t": ev["t"], "node": ev.get("node", "")})
        elif ev["kind"] == "step" and ev.get("total"):
            progress = {"text": ev["text"], "current": ev.get("current"), "total": ev["total"], "stage": ev["stage"]}
        elif ev["kind"] == "end":
            ended = {"status": ev.get("status"), "text": ev["text"], "t": ev["t"]}
    return {"counts": counts, "ops": ops, "stages": stages, "nodes": nodes, "progress": progress, "end": ended,
            "last_seq": events[-1]["seq"] if events else 0, "t": events[-1]["t"] if events else 0}
