import os
import socket
from datetime import timedelta
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY', default='dev-secret-key-change-in-production')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,web', cast=lambda v: [s.strip() for s in v.split(',')])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party packages
    'rest_framework',
    'rest_framework_simplejwt',
    'django_celery_beat',
    'django_celery_results',
    
    # Local apps
    'users.apps.UsersConfig',
    'core.apps.CoreConfig',
    'events.apps.EventsConfig',
    'orders.apps.OrdersConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'config.wsgi.application'

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Host Resolution Fallback for Docker vs Local Execution
db_host_env = config('DB_HOST', default='db')
db_port_env = config('DB_PORT', default='5432')
redis_url_env = config('REDIS_URL', default='redis://redis:6379/0')
celery_broker_url_env = config('CELERY_BROKER_URL', default='redis://redis:6379/0')

try:
    socket.gethostbyname(db_host_env)
except socket.gaierror:
    db_host_env = 'localhost'
    db_port_env = '5433'  # Local host port mapping when Docker DB runs alongside local Postgres

try:
    socket.gethostbyname('redis')
except socket.gaierror:
    redis_url_env = 'redis://localhost:6379/0'
    celery_broker_url_env = 'redis://localhost:6379/0'

# Database Configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='paymob_ticketing'),
        'USER': config('DB_USER', default='paymob'),
        'PASSWORD': config('DB_PASSWORD', default='devpassword'),
        'HOST': db_host_env,
        'PORT': db_port_env,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'reserve': '10/min',
        'purchase': '5/min',
        'refund': '3/min',
        'events_list': '60/min',
    },
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
}

# SimpleJWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Cache Configuration (Redis)
REDIS_URL = redis_url_env
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Celery Configuration
CELERY_BROKER_URL = celery_broker_url_env
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'sweep-expired-reservations': {
        'task': 'orders.tasks.sweep_expired_reservations',
        'schedule': 60.0,
    },
    'daily-reconciliation': {
        'task': 'core.tasks.run_reconciliation_task',
        'schedule': crontab(hour=2, minute=0),
    },
}

# Payment Provider Setting
PAYMENT_PROVIDER_CLASS = config('PAYMENT_PROVIDER_CLASS', default='payments.providers.FakePaymentProvider')

# Alerting (brief §2: "any oversell incident triggers immediate alerting")
# Uses Django's configured EMAIL_BACKEND (console in dev; point EMAIL_HOST/etc.
# at a real SMTP relay via env vars for production - not built here, same
# documented-not-built pattern as this project's other production-hardening notes).
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='alerts@paymobtask.local')
ALERT_RECIPIENT_EMAILS = config('ALERT_RECIPIENT_EMAILS', default='ops@example.com', cast=Csv())
