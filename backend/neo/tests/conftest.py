import pytest
from django.conf import settings

from curriculum.models import Plan
from curriculum.services.import_service import PlanImportService
from neo.models import PlatformClass

# الصفان الحقيقيان: LMS ID ← (المستوى، الاسم)
CLASSES = {602598: (10, "الرياضيات 10/3"), 602728: (12, "الرياضيات 12/2")}


@pytest.fixture
def classes(db) -> dict[int, PlatformClass]:
    PlanImportService(settings.PLANS_SOURCE_DB).run()
    return {lms: PlatformClass.objects.create(lms_id=lms, name=name, plan=Plan.objects.get(grade_level=g))
            for lms, (g, name) in CLASSES.items()}
