"""
ما يخص ويندوز وأوفيس على جهاز المعلم: مجلد سطح المكتب الفعلي، والتحقق من ملف وورد بفتحه في Word نفسه.
Word يعيد عند الفتح كتابة المحتوى المربوط (التذييل من customXml)، فقراءته منه هي التحقق الصادق، والـ PDF
الناتج يراه المعلم كما سيُطبع.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

WD_EXPORT_PDF = 17


class OfficeUnavailable(RuntimeError):
    pass


def _powershell(script: str, env: dict | None = None, timeout: int = 60) -> str:
    if sys.platform != "win32":
        raise OfficeUnavailable("يتطلب ويندوز")
    prefix = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; "
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", prefix + script], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise OfficeUnavailable((r.stderr or r.stdout).strip()[:500])
    return r.stdout.strip()


def desktop_dir() -> Path:
    """[Environment]::GetFolderPath('Desktop'): قد يكون OneDrive\\Desktop لا ~/Desktop."""
    if sys.platform != "win32":
        return Path.home() / "Desktop"
    return Path(_powershell("[Environment]::GetFolderPath('Desktop')"))


_WORD_SCRIPT = r"""
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($env:NEO_DOCX, $false, $true, $false)
  $out = @{ headers = @(); footers = @(); tables = @() }
  foreach ($s in $doc.Sections) {
    foreach ($i in 1..3) {
      $out.headers += $s.Headers.Item($i).Range.Text
      $out.footers += $s.Footers.Item($i).Range.Text
    }
  }
  foreach ($t in $doc.Tables) { $out.tables += $t.Range.Text }
  # كل نصوص المستند كما يعرضها Word، ومنها مربعات النص في الرؤوس والتذييلات (التذييل المربوط داخل شكل)
  $out.stories = @()
  foreach ($story in $doc.StoryRanges) {
    $r = $story
    while ($r -ne $null) { $out.stories += $r.Text; $r = $r.NextStoryRange }
  }
  $doc.ExportAsFixedFormat($env:NEO_PDF, 17)
  $doc.Close(0)
  $out | ConvertTo-Json -Compress -Depth 3
} finally { $word.Quit() }
"""


def word_read_and_export(docx: Path, pdf: Path, timeout: int = 180) -> dict:
    """يفتح المستند في Word للقراءة فقط، ويعيد نص الرؤوس والتذييلات والجداول كما يعرضها Word، ويصدّره PDF."""
    pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        out = _powershell(_WORD_SCRIPT, {"NEO_DOCX": str(docx), "NEO_PDF": str(pdf)}, timeout)
    except subprocess.TimeoutExpired as exc:
        raise OfficeUnavailable(f"Word لم يُنهِ خلال {timeout} ث") from exc
    data = json.loads(out)
    return {k: [x for x in (v if isinstance(v, list) else [v]) if x] for k, v in data.items()}
