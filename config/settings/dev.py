from .base import *

DEBUG = True

# Enable DRF Browsable API UI in Development
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = (
    'rest_framework.renderers.JSONRenderer',
    'rest_framework.renderers.BrowsableAPIRenderer',
)

# Development email backend (prints to console)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
