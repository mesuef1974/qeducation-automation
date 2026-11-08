from django.contrib import admin
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from core.views import docs, spa

urlpatterns = [
    path("", RedirectView.as_view(url="/app/", permanent=False)),
    re_path(r"^app/(?P<path>.*)$", spa, name="app"),
    re_path(r"^docs/(?P<path>.+)$", docs, name="docs"),
    # لوحة الإدارة تحتاج ملفاتها الثابتة وDEBUG مغلق؛ الخادم محلي (LoopbackOnlyMiddleware)
    re_path(r"^static/(?P<path>.*)$", serve_static, {"insecure": True}),
    path("admin/", admin.site.urls),
    path("api/neo/", include("neo.api.urls")),
    path("api/", include("curriculum.api.urls")),
]
