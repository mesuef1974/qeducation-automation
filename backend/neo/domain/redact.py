"""
حجب الأسرار من نصوص الأخطاء قبل حفظها أو عرضها.

أخطاء Playwright تحمل «Call log» بترويسات الطلب كما أُرسلت، وفيها كوكيز جلسة منصة قطر للتعليم
(lms_session_v1 وغيرها)، ومن يملك قيمتها يدخل المنصة باسم المعلم. فلا تبقى في قاعدة البيانات ولا تظهر
في الواجهة. يبقى باقي النص (الخطأ والرابط والترويسات الأخرى) لأنه يفيد في التشخيص.
"""
import re

MASK = "«محجوب»"

# سطر ترويسة سرّية في سجل الطلب: «    - cookie: a=1; b=2»
_HEADER = re.compile(
    r"(?im)^(\s*-?\s*)(cookie|set-cookie|authorization|proxy-authorization|x-csrftoken|x-csrf-token)(\s*:\s*)\S.*$")
# قيمة كوكي جلسة في أي موضع آخر من النص (رابط أو رسالة)
_SESSION = re.compile(r"(?i)\b(lms_session_v1|browser_session|cfid|wfx_unq|sessionid|csrftoken)=[^;\s&\"']+")


def scrub(text: str | None) -> str:
    """النص نفسه بلا قيم الكوكيز وترويسات التفويض. التكرار آمن: المحجوب يبقى كما هو."""
    if not text:
        return ""
    text = _HEADER.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{MASK}", text)
    return _SESSION.sub(lambda m: f"{m.group(1)}={MASK}", text)


def has_secret(text: str | None) -> bool:
    return bool(text) and scrub(text) != text
