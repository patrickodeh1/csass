import os
from pathlib import Path
from decouple import config
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY
SECRET_KEY = config('SECRET_KEY', default='@(ggq*4*-!r=so-c=7mguzii1#hwd$26+zb!girkmvkz4_h^)&')
DEBUG = config('DEBUG', default=False, cast=bool)
#DEBUG = True
ALLOWED_HOSTS = [
    'csass-web-service-production.up.railway.app',
    'localhost',
    '127.0.0.1',
    'tracking.revenueaccelerationunit.com',
]

CSRF_TRUSTED_ORIGINS = [
    "https://csass-web-service-production.up.railway.app",
    "https://tracking.revenueaccelerationunit.com",
]


# INSTALLED APPS
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'crispy_forms',
    'django_celery_beat',
    'crispy_bootstrap5',
    'core',
    'cloudinary',
    'cloudinary_storage',
]

# MIDDLEWARE
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'csass_project.urls'


# TEMPLATES
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'csass_project.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': 'postgres.gszspbmnsorqpxenfvib',
        'PASSWORD': '&!2M!dHT$d8v&gZ',
        'HOST': 'aws-1-eu-west-1.pooler.supabase.com',
        'PORT': '5432',
        'OPTIONS': {
            'sslmode': 'require',
        },
    }
}


# CUSTOM USER MODEL
AUTH_USER_MODEL = 'core.User'

# PASSWORD VALIDATION
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# INTERNATIONALIZATION
LANGUAGE_CODE = 'en-us'
TIME_ZONE = config('TIMEZONE', default='America/New_York')
USE_I18N = True
USE_TZ = True

# CELERY CONFIGURATION
import ssl

# Get Redis URL and ensure SSL parameter is included
REDIS_URL = os.getenv("REDIS_URL", "redis://default:EduCoFGJoxTPxPEnpBzqHSvwEhXYkBgh@redis.railway.internal:6379")

# Add SSL parameter if using rediss:// and it's not already there
if REDIS_URL.startswith('rediss://') and 'ssl_cert_reqs' not in REDIS_URL:
    REDIS_URL = f"{REDIS_URL}?ssl_cert_reqs=none"

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Connection retry settings
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 10
# STATIC FILES
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
if (BASE_DIR / 'static').exists():
    STATICFILES_DIRS = [BASE_DIR / 'static']

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# MEDIA FILES
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': 'dgpi01o5n',
    'API_KEY': '795278697945195',
    'API_SECRET': 'Rn1hL1iFA853KD-HaBVC6Qic8G8',
}

DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# DEFAULT FILE STORAGE (Local)
#DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# AUTH / LOGIN
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'calendar'
LOGOUT_REDIRECT_URL = 'login'


# Google Sheets Integration
GOOGLE_KEY_FILE = config('GOOGLE_KEY_FILE', default='credentials/google-credentials.json')
SPREADSHEET_ID = config('SPREADSHEET_ID', default='')
SHEET_NAME = config('SHEET_NAME', default='Live Transfers')

# Sheet Sync Settings
SHEET_SYNC_INTERVAL_SECONDS = config('SHEET_SYNC_INTERVAL_SECONDS', default=30, cast=int)


#EMAIL SETTINGS

EMAIL_BACKEND = 'sendgrid_backend.SendgridBackend'
SENDGRID_API_KEY = config("SENDGRID_API_KEY")
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL')

# PASSWORD RESET TOKEN EXPIRY
PASSWORD_RESET_TIMEOUT = 86400  # 24 hours

# SMS SETTINGS (Twilio)
SMS_ENABLED = config('SMS_ENABLED', default=False, cast=bool)
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_FROM_NUMBER = config('TWILIO_FROM_NUMBER', default='')

# CRISPY FORMS
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# SESSION SETTINGS
SESSION_COOKIE_AGE = 28800  # 8 hours
SESSION_SAVE_EVERY_REQUEST = True

# CUSTOM SETTINGS
MAX_LOGIN_ATTEMPTS = 5
EMAIL_TIMEOUT = 5

# DEFAULT AUTO FIELD
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# LOGGING CONFIGURATION
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'core.signals': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'core.utils': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'core.tasks': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


CELERY_BEAT_SCHEDULE = {
    # Generate timeslots at midnight EST every day
    'generate-daily-timeslots-midnight': {
        'task': 'core.tasks.generate_daily_timeslots',
        'schedule': crontab(hour=0, minute=0),  # Midnight EST
        'options': {
            'expires': 3600,  # Task expires after 1 hour
        },
    },
    
    # Cleanup past slots at 1 AM EST every day
    'cleanup-past-slots-daily': {
        'task': 'core.tasks.cleanup_past_slots_task',
        'schedule': crontab(hour=1, minute=0),  # 1 AM EST
        'options': {
            'expires': 3600,
        },
    },
    
    # Cleanup old slots (2+ weeks) every Sunday at 2 AM EST
    'cleanup-old-slots-weekly': {
        'task': 'core.tasks.cleanup_old_slots_async',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Sunday 2 AM
        'options': {
            'expires': 7200,
        },
    },
    
    # NEW: Sync Google Sheets to DB every 30 seconds
    'sync-sheets-every-30-seconds': {
        'task': 'core.tasks.sync_sheet_to_db_periodic',
        'schedule': 30.0,  # Every 30 seconds
        'options': {
            'expires': 60,  # Task expires after 1 minute if not executed
        },
    },
}

