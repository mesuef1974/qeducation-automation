# تشغيل الأتمتة تلقائيًا عند الدخول إلى ويندوز، فتعمل الدورة الأسبوعية في موعدها دون تذكّر.
#   .\autostart.ps1            → تسجيل المهمة (لحسابك فقط، بلا صلاحيات مدير)
#   .\autostart.ps1 -Remove    → إلغاؤها
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "QEducationAutomation"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "أُلغي التشغيل التلقائي."
    return
}

$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { (Get-Command pwsh).Source } else { "powershell.exe" }
$script = Join-Path $PSScriptRoot "start.ps1"
$action = New-ScheduledTaskAction -Execute $shell -WorkingDirectory $PSScriptRoot `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Background"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"  # بعد استقرار الشبكة
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description "أتمتة منصة قطر للتعليم: الخادم والعامل (الدورة الأسبوعية الخميس 14:00)" -Force | Out-Null
Write-Host "سُجّل التشغيل التلقائي عند الدخول إلى ويندوز ($name). للإلغاء: .\autostart.ps1 -Remove"
