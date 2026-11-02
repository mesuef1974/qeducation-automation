import pytest

from curriculum.models import Plan
from curriculum.services.import_service import PlanImportService
from neo.services.class_service import ClassService
from neo.services.sync_service import NoActiveClasses, active_classes


def test_active_classes_and_filter(classes):
    assert {k.lms_id for k in active_classes()} == {602598, 602728}
    assert [k.lms_id for k in active_classes([602728])] == [602728]
    ClassService().set_active(602728, False)
    assert [k.lms_id for k in active_classes()] == [602598]
    with pytest.raises(NoActiveClasses):
        active_classes([602728])


def test_register_is_idempotent_and_relinks(classes):
    svc = ClassService()
    g12 = Plan.objects.get(grade_level=12)
    k, created = svc.register(602598, g12.pk)
    assert not created and k.plan == g12 and k.name == "الرياضيات 10/3"
    with pytest.raises(ValueError):
        svc.register(999, g12.pk)  # صف جديد بلا اسم
    with pytest.raises(LookupError):
        svc.register(999, 0, "س")


def test_reimport_keeps_class_links(classes, settings):
    before = {k.lms_id: k.plan_id for k in classes.values()}
    PlanImportService(settings.PLANS_SOURCE_DB).run()
    assert {k.lms_id: k.plan_id for k in active_classes()} == before
