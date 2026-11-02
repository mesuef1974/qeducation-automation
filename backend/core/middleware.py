from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseForbidden

LOOPBACK = {"127.0.0.1", "::1"}


def is_loopback(request) -> bool:
    return request.META.get("REMOTE_ADDR") in LOOPBACK


class LoopbackOnlyMiddleware:
    """يرفض أي طلب لا يأتي من الجهاز نفسه، حتى لو شُغّل الخادم على 0.0.0.0."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_loopback(request):
            return HttpResponseForbidden("Local access only")
        return self.get_response(request)


class LocalAutoLoginMiddleware:
    """يسجّل دخول مدير محلي تلقائيًا؛ الحساب بلا كلمة مرور قابلة للاستخدام."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.LOCAL_AUTO_LOGIN and is_loopback(request) and not request.user.is_authenticated:
            login(request, self._local_admin(), backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)

    @staticmethod
    def _local_admin():
        user, created = get_user_model().objects.get_or_create(
            username=settings.LOCAL_ADMIN_USERNAME,
            defaults={"is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user
