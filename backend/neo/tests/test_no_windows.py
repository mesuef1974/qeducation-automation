"""قاعدة المعلم (2026-11-07): لا نافذة PowerShell/cmd ظاهرة ولا وميضها؛ كل subprocess بلا نافذة."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {"tests", "migrations", "__pycache__"}


def _calls():
    for path in ROOT.rglob("*.py"):
        if SKIP & set(path.relative_to(ROOT).parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess" \
                    and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}:
                yield path, node


def test_every_subprocess_hides_its_window():
    bad = [f"{p.relative_to(ROOT)}:{n.lineno}" for p, n in _calls()
           if "creationflags" not in {k.arg for k in n.keywords}]
    assert not bad, f"subprocess بلا creationflags=CREATE_NO_WINDOW: {bad}"


def test_only_interactive_login_shows_a_browser():
    """المتصفح الظاهر للدخول اليدوي فقط (neo_login والعميل التفاعلي)؛ كل ما سواه headless."""
    shown = []
    for path in ROOT.rglob("*.py"):
        if SKIP & set(path.relative_to(ROOT).parts):
            continue
        if "headless=False" in path.read_text(encoding="utf-8"):
            shown.append(path.name)
    assert sorted(shown) == ["job_service.py", "neo_login.py"] or sorted(shown) == ["neo_login.py"], shown
