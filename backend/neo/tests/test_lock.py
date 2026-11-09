"""شرط المعلم: «مغلق = مفتوح» قبل أي كتابة على الدرس؛ المغلق يُتخطّى بسببه ولا يُكتب عليه؛ بلا منصة."""
from neo.infrastructure.parsers import parse_lesson_open
from neo.models import ContentProposal
from neo.services import safety
from neo.services.content_service import ContentService
from neo.tests.test_content import LMS
from neo.tests.test_tags import TagClient, _audited


def _locked_tab(lock_checked: bool, text: str) -> str:
    on = ' checked="checked"'
    return (f'<h2>مغلق</h2><input type="radio" name="default_locking" id="default_locking_show" value="Lock"'
            f'{on if lock_checked else ""} /><label>مغلق</label>'
            f'<input type="radio" name="default_locking" id="default_locking_hide" value="Unlock"'
            f'{"" if lock_checked else on} /><label>مفتوح</label><p>{text}</p>')


def test_parse_lesson_open():
    assert parse_lesson_open(_locked_tab(False, "هذا العنصر غير مغلق لأي من المستخدمين.")) is True
    assert parse_lesson_open(_locked_tab(True, "")) is False
    # مفتوح افتراضيًا لكن مغلق لمستخدمين محددين: ليس مفتوحًا للجميع
    assert parse_lesson_open(_locked_tab(False, "المستخدمون المغلق عليهم: ...")) is False
    # شكل غير مألوف: لا تخمين
    assert parse_lesson_open("<div>صفحة أخرى</div>") is None
    assert parse_lesson_open('<input type="radio" name="default_locking" value="Lock">') is None


def test_locked_lesson_is_skipped_and_never_written(classes, settings, tmp_path):
    k = _audited(classes, settings, tmp_path)
    run = ContentService().record_plan(k, list(k.lessons.all()), {})
    ContentService().approve(run.pk)
    client = TagClient()
    client.locked = True
    ContentService().apply(run, lambda: client)
    assert client.calls == []
    p = run.content_proposals.get()
    assert p.status == ContentProposal.Status.SKIPPED and p.error == safety.LOCKED_SKIP
    assert k.lms_id == LMS
