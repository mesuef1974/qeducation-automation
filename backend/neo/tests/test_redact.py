"""حجب كوكيز الجلسة وترويسات التفويض من نصوص الأخطاء: عند الحفظ، وعند بدء العامل، وعند العرض."""
import pytest

from neo.api.serializers import JobSerializer
from neo.domain.redact import MASK, has_secret, scrub
from neo.models import Job
from neo.services.job_service import JobService

from .test_api import LMS, maker

# شكل خطأ Playwright كما خُزّن فعلًا، بقيم وهمية
SECRET = "c2VjcmV0LXNlc3Npb24tdmFsdWUtZm9yLXRlc3Q"
PLAYWRIGHT = (
    "APIRequestContext.get: Request context disposed.\nCall log:\n"
    "  - \u2192 GET https://qeducation.edu.gov.qa/teacher_lesson/show/602598?lesson_id=1\n"
    "    - user-agent: Mozilla/5.0 HeadlessChrome/156.0.0.0\n"
    "    - accept: */*\n"
    f"    - cookie: wfx_unq=abc123; cfid=442163%7C%7Cxyz; browser_session=6c2007fd-0000; lms_session_v1={SECRET}"
)


def test_scrub_masks_cookie_header_and_keeps_the_rest():
    out = scrub(PLAYWRIGHT)
    assert SECRET not in out and "6c2007fd" not in out and "abc123" not in out
    assert f"cookie: {MASK}" in out
    assert "Request context disposed" in out and "lesson_id=1" in out and "user-agent" in out
    assert scrub(out) == out and not has_secret(out) and has_secret(PLAYWRIGHT)


@pytest.mark.parametrize("text", [
    f"Authorization: Bearer {SECRET}",
    f"\u062e\u0637\u0623 \u0641\u064a https://x.test/?lms_session_v1={SECRET}&a=1",
    f"set-cookie: lms_session_v1={SECRET}; Path=/",
])
def test_scrub_other_shapes(text):
    assert SECRET not in scrub(text)


def test_scrub_leaves_plain_errors():
    plain = "انتهت الجلسة - شغّل: python manage.py neo_login"
    assert scrub(plain) == plain and scrub("") == "" and scrub(None) == ""


def test_run_stores_scrubbed_error(classes):
    svc = JobService()
    job = svc.run(svc.enqueue(Job.Kind.VERIFY, {"classes": [LMS]})[0], maker(RuntimeError(PLAYWRIGHT)))
    job.refresh_from_db()
    assert job.status == Job.Status.FAILED and SECRET not in job.error and "Request context disposed" in job.error


def test_recover_scrubs_stored_errors(classes):
    old = Job.objects.create(kind=Job.Kind.VERIFY, key="old", status=Job.Status.FAILED, error=PLAYWRIGHT[:1000])
    plain = Job.objects.create(kind=Job.Kind.VERIFY, key="plain", status=Job.Status.FAILED, error="أُلغيت قبل التشغيل")
    JobService().recover()
    old.refresh_from_db()
    plain.refresh_from_db()
    assert SECRET not in old.error and f"cookie: {MASK}" in old.error and plain.error == "أُلغيت قبل التشغيل"


def test_serializer_never_shows_secret(classes):
    job = Job.objects.create(kind=Job.Kind.VERIFY, key="x", status=Job.Status.FAILED, error=PLAYWRIGHT)
    assert SECRET not in JobSerializer(job).data["error"]
