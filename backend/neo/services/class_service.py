"""سجل الصفوف: ربط صف المنصة بخطته وتفعيله أو إيقافه. Idempotent: الإضافة المتكررة تحدّث ولا تكرر."""
from curriculum.models import Plan
from neo.models import PlatformClass


class ClassService:
    def register(self, lms_id: int, plan_id: int, name: str | None = None) -> tuple[PlatformClass, bool]:
        plan = Plan.objects.filter(pk=plan_id).first()
        if plan is None:
            raise LookupError(f"لا توجد خطة #{plan_id}")
        existing = PlatformClass.objects.filter(lms_id=lms_id).first()
        if not name and not existing:
            raise ValueError("اسم الصف مطلوب عند الإضافة الأولى (كما يظهر على المنصة)")
        defaults = {"plan": plan, "active": True}
        if name:
            defaults["name"] = name
        return PlatformClass.objects.update_or_create(lms_id=lms_id, defaults=defaults)

    def set_active(self, lms_id: int, active: bool) -> PlatformClass:
        n = PlatformClass.objects.filter(lms_id=lms_id).update(active=active)
        if not n:
            raise LookupError(f"الصف {lms_id} غير مسجل")
        return PlatformClass.objects.get(lms_id=lms_id)
