"""
إعدادات المشروع - تشغيل محلي فقط (loopback) بلا تسجيل دخول.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent


def _secret_key() -> str:
    if key := os.environ.get("DJANGO_SECRET_KEY"):
        return key
    path = BASE_DIR / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "curriculum.apps.CurriculumConfig",
    "neo.apps.NeoConfig",
]

MIDDLEWARE = [
    "core.middleware.LoopbackOnlyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.LocalAutoLoginMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # قبل قوالب التطبيقات: يتقدّم admin/base_site.html هنا على قالب django.contrib.admin
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 30},  # العامل والواجهة والأوامر تتشارك الملف: انتظار القفل بدل الانهيار
    }
}

# ملفات الخطط الموحّدة (Excel): مجلد <العام>/ف<الفصل>/ - المصدر المعتمد للاستيراد
PLANS_DIR = Path(os.environ.get("PLANS_DIR", PROJECT_ROOT / "plans"))

# منصة قطر للتعليم: ملف تعريف المتصفح (جلسة الدخول)
NEO_PROFILE_DIR = BASE_DIR / ".neo_profile"
NEO_BROWSER_CHANNEL = "msedge"
# سياسة الإسناد (المهمة 2) - اختيار المعلم: يظهر صباح يوم الدرس، يستحق بعد يومين، يُقبل المتأخر
NEO_ASSIGN_POLICY = {"due_days": 2, "allow_late": True}
# سياسة النشر (المهمة 3) - اختيار المعلم: يظهر كل درس مؤرخ، وكل درس يمنح عند إنجازه ما تمنحه الدروس الأولى
NEO_PUBLISH_POLICY = {"show_dated": True, "points": 5, "game": "نجوم الرياضيات", "notification": "Popup"}
# الدورة الأسبوعية (قرار المعلم: تلقائي مع تقرير بعده) - الخميس 14:00، تُستدرك حتى صباح الأحد.
# يُعتمد آليًا ما يقع في 14 يومًا القادمة بلا تنبيه، وما زاد على 20 تغييرًا في مرحلة يبقى للمراجعة
NEO_WEEKLY = {"enabled": True, "weekday": 3, "hour": 14, "catchup_hours": 66, "window_days": 14, "max_per_stage": 20}
# محرك المحتوى: الصور المولّدة (خارج المستودع) ومصادر الصف التي تُذكر في قسم التهيئة
MEDIA_ROOT = BASE_DIR / "media"
NEO_CONTENT_SOURCES = ("كتاب الطالب", "الكتاب التفاعلي")
# الصفوف وربطها بالخطط في قاعدة البيانات (PlatformClass) لا هنا

# دخول تلقائي كمدير - يعمل فقط لطلبات loopback
LOCAL_AUTO_LOGIN = True
LOCAL_ADMIN_USERNAME = "admin"

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Qatar"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# هوية المشروع (الألوان والخطوط والثيم) مصدرها الوحيد docs/assets، وتُخدَم للوحة الإدارة من جذر static/.
# بلا بادئة: FileSystemFinder يقارن البادئة بـ os.sep فلا يجد "brand/x.css" على Windows
STATICFILES_DIRS = [PROJECT_ROOT / "docs" / "assets"]
# الواجهة الأمامية المبنية، تُخدم على /app/ (core.views.spa)
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
# صفحات docs/ (تقرير SWOT وصفحة الأتمتة) على /docs/، تعرضها الواجهة داخل إطار
DOCS_DIR = PROJECT_ROOT / "docs"
# خادم Vite أثناء التطوير (npm run dev) يمرّر الطلبات إلى هنا؛ Origin فيها منفذه
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
# Secure يتطلب HTTPS؛ الخادم محلي على http://127.0.0.1
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "UNICODE_JSON": True,
}
