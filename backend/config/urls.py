from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from core.views import docs, spa

urlpatterns = [
    path("", RedirectView.as_view(url="/app/", permanent=False)),
    re_path(r"^app/(?P<path>.*)$", spa, name="app"),
    re_path(r"^docs/(?P<path>.+)$", docs, name="docs"),
    path("admin/", admin.site.urls),
    path("api/neo/", include("neo.api.urls")),
    path("api/", include("curriculum.api.urls")),
]
