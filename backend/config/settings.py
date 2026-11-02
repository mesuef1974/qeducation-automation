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
        "DIRS": [],
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
    }
}

# قاعدة الخطط المبنية بـ db/build_db.py - مصدر الاستيراد
PLANS_SOURCE_DB = Path(os.environ.get(
    "PLANS_SOURCE_DB", PROJECT_ROOT / "db" / "math_plans_2026_2027.db"
))

# منصة قطر للتعليم: ملف تعريف المتصفح (جلسة الدخول)
NEO_PROFILE_DIR = BASE_DIR / ".neo_profile"
NEO_BROWSER_CHANNEL = "msedge"
# سياسة الإسناد (المهمة 2) - اختيار المعلم: يظهر صباح يوم الدرس، يستحق بعد يومين، يُقبل المتأخر
NEO_ASSIGN_POLICY = {"due_days": 2, "allow_late": True}
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
