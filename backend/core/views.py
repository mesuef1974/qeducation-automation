"""
الواجهة الأمامية المبنية (frontend/dist) على /app/. أي مسار ليس ملفًا يعيد index.html،
فيتولى Vue Router التوجيه (/app/review/publish ...). البناء: cd frontend && npm run build

وصفحات docs/ (التقرير وصفحة الأتمتة) على /docs/، تعرضها الواجهة داخل إطار من الأصل نفسه.
"""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404, HttpResponse
from django.utils._os import safe_join
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.static import serve

# ما يُخدم من docs/: صفحات الويب وما تحتاجه فقط، لا ملفات Markdown ولا غيرها
DOCS_SUFFIXES = {".html", ".css", ".js", ".jpg", ".jpeg", ".png", ".svg", ".webp", ".woff2"}


def _file_in(root: Path, path: str) -> bool:
    try:
        return Path(safe_join(root, path)).is_file()  # يرفض الخروج من المجلد (../)
    except SuspiciousFileOperation as exc:
        raise Http404 from exc


def spa(request, path: str = ""):
    root = settings.FRONTEND_DIST
    if path and _file_in(root, path):
        return serve(request, path, document_root=root)
    index = root / "index.html"
    if not index.is_file():
        return HttpResponse("الواجهة لم تُبنَ بعد: cd frontend && npm run build", status=503,
                            content_type="text/plain; charset=utf-8")
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"  # الملفات المسمّاة بالبصمة تُخزَّن؛ الصفحة نفسها تُفحص دائمًا
    return response


@xframe_options_sameorigin
def docs(request, path: str):
    root = settings.DOCS_DIR
    if Path(path).suffix.lower() not in DOCS_SUFFIXES or not _file_in(root, path):
        raise Http404
    return serve(request, path, document_root=root)
