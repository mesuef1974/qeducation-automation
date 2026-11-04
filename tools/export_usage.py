"""
يصدّر أرقام استهلاك جلسة Claude من سجلها (Claude Code *.jsonl) إلى backend/usage/ لتبويب «الاستهلاك»:
الوقت والنموذج والرموز وأسماء الأدوات فقط، بلا أي نص من المحادثة.

    python tools/export_usage.py <سجل-الجلسة.jsonl> [مجلد-الإخراج]
"""
import json
import sys
from pathlib import Path


def main(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / src.name
    n = 0
    with src.open(encoding="utf-8", errors="replace") as f, dest.open("w", encoding="utf-8") as w:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            m = r.get("message") or {}
            if r.get("type") != "assistant" or not m.get("usage"):
                continue
            tools = [{"type": "tool_use", "name": c.get("name", "")} for c in m.get("content") or []
                     if isinstance(c, dict) and c.get("type") == "tool_use"]
            keep = {"type": "assistant", "timestamp": r.get("timestamp"), "sessionId": r.get("sessionId"),
                    "requestId": r.get("requestId"),
                    "message": {"id": m.get("id"), "model": m.get("model"), "usage": m["usage"], "content": tools}}
            w.write(json.dumps(keep, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} خطوة → {dest}")
    return dest


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "backend" / "usage")
