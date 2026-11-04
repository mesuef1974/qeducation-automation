# تشغيل الأتمتة تلقائيًا مع ويندوز، ومراقبتها كل 10 دقائق فتعود إن توقفت (العامل في معايير الأتمتة).
#   .\autostart.ps1            → تسجيل المهمة أو تحديثها (لحسابك فقط، بلا صلاحيات مدير)
#   .\autostart.ps1 -Remove    → إلغاؤها، ولا يعيدها start.ps1 بعد ذلك
# start.ps1 يسجّلها أو يحدّثها وحده إن غابت أو كان إصدارها أقدم، ما لم تُلغَ.
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "QEducationAutomation"
$optOut = Join-Path $PSScriptRoot ".no_autostart"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    New-Item -ItemType File -Path $optOut -Force | Out-Null
    Write-Host "أُلغي التشغيل التلقائي."
    return
}
Remove-Item $optOut -ErrorAction SilentlyContinue

$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { (Get-Command pwsh).Source } else { "powershell.exe" }
$script = Join-Path $PSScriptRoot "start.ps1"
$action = New-ScheduledTaskAction -Execute $shell -WorkingDirectory $PSScriptRoot `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Background"
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT1M"  # بعد استقرار الشبكة
# المراقبة: كل 10 دقائق يشغّل ما ليس يعمل فقط (الخادم، العامل)، فيعود العامل إن توقف
$watch = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $watch) -Settings $settings `
    -Description "أتمتة منصة قطر للتعليم (v2): الخادم والعامل عند الدخول إلى ويندوز وكل 10 دقائق إن توقفا؛ الدورة الأسبوعية الاثنين 7:00" `
    -Force | Out-Null
Write-Host "سُجّل التشغيل التلقائي والمراقبة كل 10 دقائق ($name). للإلغاء: .\autostart.ps1 -Remove"
