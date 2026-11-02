"""
الواجهة الأمامية المبنية (frontend/dist) على /app/. أي مسار ليس ملفًا يعيد index.html،
فيتولى Vue Router التوجيه (/app/review/publish ...). البناء: cd frontend && npm run build
"""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404, HttpResponse
from django.utils._os import safe_join
from django.views.static import serve


def spa(request, path: str = ""):
    root = settings.FRONTEND_DIST
    if path:
        try:
            is_file = Path(safe_join(root, path)).is_file()  # يرفض الخروج من المجلد (../)
        except SuspiciousFileOperation as exc:
            raise Http404 from exc
        if is_file:
            return serve(request, path, document_root=root)
    index = root / "index.html"
    if not index.is_file():
        return HttpResponse("الواجهة لم تُبنَ بعد: cd frontend && npm run build", status=503,
                            content_type="text/plain; charset=utf-8")
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"  # الملفات المسمّاة بالبصمة تُخزَّن؛ الصفحة نفسها تُفحص دائمًا
    return response
