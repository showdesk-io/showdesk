"""Base Django settings for Showdesk."""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")

# Application definition
DJANGO_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "django_extensions",
    "storages",
    "channels",
]

LOCAL_APPS = [
    "apps.core",
    "apps.organizations",
    "apps.tickets",
    "apps.videos",
    "apps.knowledge_base",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

# Custom user model
AUTH_USER_MODEL = "organizations.User"

# Database
import dj_database_url  # noqa: E402

DATABASES = {
    "default": dj_database_url.config(
        default="postgres://showdesk:showdesk@localhost:5432/showdesk",
        conn_max_age=600,
    )
}

# Password validation — disabled (OTP-only authentication)
AUTH_PASSWORD_VALIDATORS = []

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =============================================================================
# Django REST Framework
# =============================================================================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

# =============================================================================
# JWT
# =============================================================================
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=60, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# =============================================================================
# CORS
# =============================================================================
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://localhost:5173",
    cast=Csv(),
)

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:40080,https://localhost:40443",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "x-csrftoken",
    "x-requested-with",
    "x-widget-token",
    "x-widget-session",
    "x-showdesk-org",
]

# =============================================================================
# Channels (WebSocket)
# =============================================================================
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [config("REDIS_URL", default="redis://localhost:6379/0")],
        },
    },
}

# =============================================================================
# Celery
# =============================================================================
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default="redis://localhost:6379/2"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True

# Celery Beat schedule
CELERY_BEAT_SCHEDULE = {
    "cleanup-expired-videos": {
        "task": "apps.videos.tasks.cleanup_expired_videos",
        "schedule": 60 * 60 * 6,  # Every 6 hours
    },
    "recheck-dns-pending-domains": {
        "task": "apps.organizations.tasks.recheck_dns_pending_domains",
        "schedule": 60 * 15,  # Every 15 minutes
    },
}

# =============================================================================
# S3-compatible Storage
# =============================================================================
S3_ENDPOINT_URL = config("S3_ENDPOINT_URL", default="http://localhost:9000")
S3_PUBLIC_URL = config("S3_PUBLIC_URL", default="")
S3_ACCESS_KEY_ID = config("S3_ACCESS_KEY_ID", default="showdesk")
S3_SECRET_ACCESS_KEY = config("S3_SECRET_ACCESS_KEY", default="showdesk-secret")
S3_BUCKET_NAME = config("S3_BUCKET_NAME", default="showdesk-media")
S3_REGION = config("S3_REGION", default="us-east-1")

STORAGES = {
    "default": {
        "BACKEND": "apps.core.storage.PublicURLS3Storage",
        "OPTIONS": {
            "endpoint_url": S3_ENDPOINT_URL,
            "access_key": S3_ACCESS_KEY_ID,
            "secret_key": S3_SECRET_ACCESS_KEY,
            "bucket_name": S3_BUCKET_NAME,
            "region_name": S3_REGION,
            "file_overwrite": False,
            "default_acl": "private",
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# =============================================================================
# LiveKit
# =============================================================================
LIVEKIT_URL = config("LIVEKIT_URL", default="ws://localhost:7880")
LIVEKIT_API_KEY = config("LIVEKIT_API_KEY", default="devkey")
LIVEKIT_API_SECRET = config("LIVEKIT_API_SECRET", default="devsecret")

# =============================================================================
# Video Processing
# =============================================================================
VIDEO_MAX_DURATION_SECONDS = config("VIDEO_MAX_DURATION_SECONDS", default=600, cast=int)
VIDEO_MAX_FILE_SIZE_MB = config("VIDEO_MAX_FILE_SIZE_MB", default=500, cast=int)
VIDEO_EXPIRATION_DAYS = config("VIDEO_EXPIRATION_DAYS", default=90, cast=int)
VIDEO_THUMBNAIL_WIDTH = config("VIDEO_THUMBNAIL_WIDTH", default=320, cast=int)
VIDEO_THUMBNAIL_HEIGHT = config("VIDEO_THUMBNAIL_HEIGHT", default=180, cast=int)

# =============================================================================
# AI Features (off by default for self-hosted)
# =============================================================================
AI_ENABLED = config("AI_ENABLED", default=False, cast=bool)
WHISPER_MODEL_SIZE = config("WHISPER_MODEL_SIZE", default="base")
WHISPER_DEVICE = config("WHISPER_DEVICE", default="cpu")

# =============================================================================
# Feature Flags
# =============================================================================
FEATURE_AI_TRANSCRIPTION = config("FEATURE_AI_TRANSCRIPTION", default=False, cast=bool)
FEATURE_AI_TRIAGE = config("FEATURE_AI_TRIAGE", default=False, cast=bool)
FEATURE_AI_SMART_REDACTION = config(
    "FEATURE_AI_SMART_REDACTION", default=False, cast=bool
)
FEATURE_AI_SENTIMENT_ANALYSIS = config(
    "FEATURE_AI_SENTIMENT_ANALYSIS", default=False, cast=bool
)

# =============================================================================
# Telemetry (opt-in only)
# =============================================================================
TELEMETRY_ENABLED = config("TELEMETRY_ENABLED", default=False, cast=bool)

# =============================================================================
# Email
# =============================================================================
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@showdesk.io")

# SMTP settings (when using django.core.mail.backends.smtp.EmailBackend)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.example.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

# Anymail settings (when using anymail.backends.mailjet.EmailBackend)
ANYMAIL = {
    "MAILJET_API_KEY": config("MAILJET_API_KEY", default=""),
    "MAILJET_SECRET_KEY": config("MAILJET_SECRET_KEY", default=""),
}

# Frontend URL for links in emails
SITE_URL = config("SITE_URL", default="http://localhost")

# =============================================================================
# Brand
# =============================================================================
# Brand identity used in transactional emails and other server-rendered
# surfaces (Django admin OTP login, etc.). Per-org overrides happen at the
# Organization level (see apps.organizations.models.Organization). All values
# are env-overridable so a self-hosted deployment can re-skin without forking.
BRAND_NAME = config("BRAND_NAME", default="Showdesk")
BRAND_PRIMARY_COLOR = config("BRAND_PRIMARY_COLOR", default="#6366F1")
BRAND_PRIMARY_COLOR_DARK = config("BRAND_PRIMARY_COLOR_DARK", default="#4F46E5")
BRAND_TEXT_COLOR = config("BRAND_TEXT_COLOR", default="#0F172A")
BRAND_MUTED_COLOR = config("BRAND_MUTED_COLOR", default="#64748B")
BRAND_BACKGROUND_COLOR = config("BRAND_BACKGROUND_COLOR", default="#F1F5F9")
BRAND_CARD_BACKGROUND_COLOR = config("BRAND_CARD_BACKGROUND_COLOR", default="#FFFFFF")
BRAND_BORDER_COLOR = config("BRAND_BORDER_COLOR", default="#E2E8F0")
# Email logo: external URL (Stripe-style — embedding as CID adds an unwanted
# "attached file" indicator in many mail clients). Empty default → helper
# falls back to f"{SITE_URL}/static/brand/logo.png", which is served by
# Django from backend/static/brand/ (Caddy proxies /static/* to the backend
# in dev; collectstatic + web server in prod). Set BRAND_LOGO_URL explicitly
# when the asset lives on a different origin (CDN, marketing site, etc.).
BRAND_LOGO_URL = config("BRAND_LOGO_URL", default="")

# =============================================================================
# OTP Authentication
# =============================================================================
OTP_LENGTH = config("OTP_LENGTH", default=6, cast=int)
OTP_EXPIRY_SECONDS = config("OTP_EXPIRY_SECONDS", default=600, cast=int)
