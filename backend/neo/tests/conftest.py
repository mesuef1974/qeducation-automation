import pytest
from django.conf import settings

from curriculum.models import Plan
from curriculum.services.import_service import PlanImportService
from neo.models import PlatformClass

# الصفان الحقيقيان: LMS ID ← (المستوى، الاسم)
CLASSES = {602598: (10, "الرياضيات 10/3"), 602728: (12, "الرياضيات 12/2")}


@pytest.fixture
def classes(db) -> dict[int, PlatformClass]:
    PlanImportService(settings.PLANS_DIR).run()
    return {lms: PlatformClass.objects.create(lms_id=lms, name=name, plan=Plan.objects.get(grade_level=g))
            for lms, (g, name) in CLASSES.items()}


@pytest.fixture(autouse=True)
def live_dir(settings, tmp_path):
    """البث الحي يكتب في مجلد مؤقت أثناء الاختبارات، لا في media/ الحقيقي."""
    settings.NEO_LIVE_DIR = tmp_path / "live"
    return settings.NEO_LIVE_DIR
