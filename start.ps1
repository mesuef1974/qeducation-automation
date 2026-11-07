# تشغيل الأتمتة بأمر واحد: .\start.ps1
# يشغّل ما ليس يعمل فقط (الخادم، العامل)، كلًّا في نافذة، ثم يفتح الموقع. الإيقاف: أغلق النافذة أو Ctrl+C فيها.
# -Background: للتشغيل عند الدخول إلى ويندوز (autostart.ps1)؛ نوافذ مصغّرة ولا يُفتح الموقع.
param([switch]$Background)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$site = "http://127.0.0.1:8777"
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }

# التشغيل مع ويندوز والمراقبة كل 10 دقائق (v2): يُسجَّل أو يُحدَّث مرة واحدة، ما لم يلغه المعلم (autostart.ps1 -Remove)
if (-not (Test-Path (Join-Path $root ".no_autostart"))) {
    $task = Get-ScheduledTask -TaskName "QEducationAutomation" -ErrorAction SilentlyContinue
    if (-not $task -or $task.Description -notlike "*(v2)*") {
        try { & (Join-Path $root "autostart.ps1") | Out-Null } catch { Write-Host "تعذّر تسجيل التشغيل التلقائي: $_" }
    }
}

function Start-Window([string]$title, [string]$command) {
    $style = if ($Background) { "Minimized" } else { "Normal" }
    Start-Process $shell -WorkingDirectory $backend -WindowStyle $style -ArgumentList "-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle = '$title'; $command"
}

function Get-Session {
    try { Invoke-RestMethod "$site/api/neo/session/" -TimeoutSec 2 } catch { $null }
}

# الواجهة المبنية (أول مرة فقط)
if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
    Write-Host "بناء الواجهة لأول مرة..."
    Push-Location (Join-Path $root "frontend")
    try { npm install --no-fund --no-audit; npm run build } finally { Pop-Location }
}

# قاعدة البيانات محدّثة قبل أن يعمل الخادم أو العامل
Push-Location $backend
try { python manage.py migrate --noinput | Out-Null } finally { Pop-Location }

# الخادم
$session = Get-Session
if ($session) {
    Write-Host "الخادم يعمل مسبقًا."
} else {
    Start-Window "الخادم" "python manage.py runserver 127.0.0.1:8777"
    for ($i = 0; $i -lt 30 -and -not $session; $i++) { Start-Sleep -Seconds 1; $session = Get-Session }
    if (-not $session) { throw "لم يستجب الخادم على $site؛ راجع نافذة الخادم." }
    Write-Host "شُغّل الخادم."
}

# العامل (من نبضه، فلا يُشغَّل عاملان على ملف الدخول نفسه)
if ($session.worker_alive) {
    Write-Host "العامل يعمل مسبقًا."
} else {
    Start-Window "العامل" "python manage.py neo_worker"
    Write-Host "شُغّل العامل."
}

if (-not $Background) { Start-Process "$site/" }
