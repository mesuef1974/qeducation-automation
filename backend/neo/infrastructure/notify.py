"""
تنبيهات ويندوز الأصلية (الخطوتان 0 و9): بلا برامج إضافية، عبر PowerShell 5 وواجهة Windows.UI.Notifications، ولكل
تنبيه زر يفتح صفحة في الموقع المحلي. لا شيء خارج ويندوز أو حين NEO_NOTIFY=False (الاختبارات)، والتنبيه لا يوقف العمل.
"""
import base64
import subprocess
import sys
import time
from xml.sax.saxutils import escape, quoteattr

from django.conf import settings

# معرّف تطبيق PowerShell المسجّل في ويندوز: تنبيه من سكربت دون تسجيل تطبيق جديد
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
SCRIPT = (
    "$x=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'));"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
    "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
    "$d=New-Object Windows.Data.Xml.Dom.XmlDocument;$d.LoadXml($x);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}')"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($d))"
)
_last: dict[str, float] = {}


def app_url(path: str = "") -> str:
    return getattr(settings, "NEO_APP_URL", "http://127.0.0.1:8765/app/") + path.lstrip("/")


def toast_xml(title: str, body: str, button: tuple[str, str] | None = None) -> str:
    """نص التنبيه بزر يفتح رابطًا (والنقر على التنبيه نفسه يفتحه كذلك)."""
    url = button[1] if button else app_url()
    actions = (f"<actions><action content={quoteattr(button[0])} activationType=\"protocol\" "
               f"arguments={quoteattr(url)}/></actions>") if button else ""
    return (f"<toast activationType=\"protocol\" launch={quoteattr(url)}><visual><binding template=\"ToastGeneric\">"
            f"<text>{escape(title)}</text><text>{escape(body)}</text></binding></visual>{actions}</toast>")


def toast(title: str, body: str, button: tuple[str, str] | None = None, key: str = "", every_s: float = 0) -> bool:
    """يرسل التنبيه ويعيد True؛ key وevery_s يمنعان تكرار التنبيه نفسه أكثر من مرة في المدة."""
    if sys.platform != "win32" or not getattr(settings, "NEO_NOTIFY", True):
        return False
    if key and every_s and time.monotonic() - _last.get(key, -1e9) < every_s:
        return False
    try:
        b64 = base64.b64encode(toast_xml(title, body, button).encode("utf-8")).decode("ascii")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        SCRIPT.replace("{b64}", b64).replace("{app}", APP_ID)],
                       capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001 - التنبيه لا يوقف العمل أبدًا
        return False
    if key:
        _last[key] = time.monotonic()
    return True
