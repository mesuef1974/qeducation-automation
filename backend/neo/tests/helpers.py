"""مساعدات الاختبارات."""
from django.db.models import F

from neo.models import PlatformLesson

TEST_CODE = "اختبار"


def confirm_matches(klass) -> None:
    """المعلم أكّد مطابقة دروس الصف مرة واحدة (الخطوة 1)؛ ما بلا مطابقة آلية يُربط يدويًا ببند الاختبار."""
    lessons = PlatformLesson.objects.filter(klass=klass)
    lessons.exclude(match_code="").update(confirmed_code=F("match_code"))
    lessons.filter(match_code="", override_code="").update(override_code=TEST_CODE)
