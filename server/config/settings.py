import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-only-change-before-deploy")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "identity.apps.IdentityConfig",
    "sales.apps.SalesConfig",
    "inventory.apps.InventoryConfig",
    "accounting.apps.AccountingConfig",
    "billing.apps.BillingConfig",
    "purchasing.apps.PurchasingConfig",
    "support.apps.SupportConfig",
    "repairs.apps.RepairsConfig",
    "expenses.apps.ExpensesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates", BASE_DIR.parent / "dist"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "redmagna"),
        "USER": os.environ.get("POSTGRES_USER", "redmagna"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "local-only-change-before-deploy"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/data/media"))
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["identity.authentication.SessionTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}
ERP_API_TOKEN_TTL_HOURS = int(os.environ.get("ERP_API_TOKEN_TTL_HOURS", "12"))

SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
USE_HTTPS_PROXY = os.environ.get("DJANGO_USE_HTTPS_PROXY", "false").lower() == "true"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if USE_HTTPS_PROXY else None
SECURE_COOKIES = os.environ.get("DJANGO_SECURE_COOKIES", "false").lower() == "true"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
APP_BIND_ADDRESS = os.environ.get("APP_BIND_ADDRESS", "0.0.0.0").strip()

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "false").lower() == "true"
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.environ.get("EMAIL_FROM", "").strip()
SUPPORT_IMAP_HOST = os.environ.get("SUPPORT_IMAP_HOST", "").strip()
SUPPORT_IMAP_PORT = int(os.environ.get("SUPPORT_IMAP_PORT", "993"))
SUPPORT_IMAP_USERNAME = os.environ.get("SUPPORT_IMAP_USERNAME", "").strip()
SUPPORT_IMAP_PASSWORD = os.environ.get("SUPPORT_IMAP_PASSWORD", "")
SUPPORT_IMAP_MAILBOX = os.environ.get("SUPPORT_IMAP_MAILBOX", "INBOX").strip() or "INBOX"
SUPPORT_IMAP_AUTH_SERV_ID = os.environ.get("SUPPORT_IMAP_AUTH_SERV_ID", "").strip().lower()
ERP_PUBLIC_URL = os.environ.get("ERP_PUBLIC_URL", "").strip()
ERP_PUBLIC_LEADS_ENABLED = os.environ.get("ERP_PUBLIC_LEADS_ENABLED", "false").strip().lower() == "true"
ERP_PRIVACY_URL = os.environ.get("ERP_PRIVACY_URL", "").strip()
CRM_LEAD_NOTIFICATION_EMAIL = os.environ.get("CRM_LEAD_NOTIFICATION_EMAIL", "").strip()
BILLING_REMINDERS_ENABLED = os.environ.get("BILLING_REMINDERS_ENABLED", "false").strip().lower() == "true"
BILLING_REMINDER_DAYS_AHEAD = int(os.environ.get("BILLING_REMINDER_DAYS_AHEAD", "3"))

# FEL Premium SOAP integration stays on its demo endpoint by default. Production
# requests require an explicit second switch so an environment typo cannot stamp
# real CFDI documents unexpectedly.
FEL_ENVIRONMENT = os.environ.get("FEL_ENVIRONMENT", "test").strip().lower()
FEL_TIMBRADO_USER = os.environ.get("FEL_TIMBRADO_USER", "")
FEL_TIMBRADO_PASSWORD = os.environ.get("FEL_TIMBRADO_PASSWORD", "")
FEL_ALLOW_PRODUCTION = os.environ.get("FEL_ALLOW_PRODUCTION", "false").lower() == "true"
# FEL cancellations reach the SAT directly; the provider documents no test
# environment. Both switches must be explicitly enabled before a user request.
FEL_ALLOW_CANCELLATION = os.environ.get("FEL_ALLOW_CANCELLATION", "false").lower() == "true"
FEL_CANCEL_PFX_BASE64 = os.environ.get("FEL_CANCEL_PFX_BASE64", "")
FEL_CANCEL_PFX_PASSWORD = os.environ.get("FEL_CANCEL_PFX_PASSWORD", "")
CFDI_ISSUER_RFC = os.environ.get("CFDI_ISSUER_RFC", "")
CFDI_ISSUER_NAME = os.environ.get("CFDI_ISSUER_NAME", "")
CFDI_ISSUER_FISCAL_REGIME = os.environ.get("CFDI_ISSUER_FISCAL_REGIME", "")
CFDI_ISSUER_POSTAL_CODE = os.environ.get("CFDI_ISSUER_POSTAL_CODE", "")
CFDI_ALLOW_BORDER_8_RATE = os.environ.get("CFDI_ALLOW_BORDER_8_RATE", "false").lower() == "true"
CFDI_BORDER_8_REVIEWED_POSTAL_CODES = {
    code.strip()
    for code in os.environ.get("CFDI_BORDER_8_REVIEWED_POSTAL_CODES", "").split(",")
    if code.strip()
}
ERP_COMPANY_NAME = os.environ.get("ERP_COMPANY_NAME", "Redmagna").strip() or "Redmagna"
ERP_COMPANY_LEGAL_NAME = os.environ.get("ERP_COMPANY_LEGAL_NAME", "").strip() or CFDI_ISSUER_NAME.strip()
ERP_COMPANY_RFC = os.environ.get("ERP_COMPANY_RFC", "").strip() or CFDI_ISSUER_RFC.strip()
ERP_COMPANY_ADDRESS = os.environ.get("ERP_COMPANY_ADDRESS", "").strip()
ERP_COMPANY_PHONE = os.environ.get("ERP_COMPANY_PHONE", "").strip()
ERP_COMPANY_EMAIL = os.environ.get("ERP_COMPANY_EMAIL", "").strip() or DEFAULT_FROM_EMAIL
ERP_COMPANY_WEBSITE = os.environ.get("ERP_COMPANY_WEBSITE", "").strip()
CFDI_PROVIDER_CODE = os.environ.get("CFDI_PROVIDER_CODE", "fel-premium")
CFDI_CSD_CERT_PATH = os.environ.get("CFDI_CSD_CERT_PATH", "/run/secrets/fiscal/redmagna.cer")
CFDI_CSD_KEY_PATH = os.environ.get("CFDI_CSD_KEY_PATH", "/run/secrets/fiscal/redmagna.key")
CFDI_CSD_PASSWORD_FILE = os.environ.get("CFDI_CSD_PASSWORD_FILE", "/run/secrets/fiscal/csd_password")
