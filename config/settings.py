import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = False
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    keyfile = BASE_DIR / '.local-secret'
    if not keyfile.exists():
        from django.core.management.utils import get_random_secret_key
        keyfile.write_text(get_random_secret_key())
        keyfile.chmod(0o600)
    SECRET_KEY = keyfile.read_text()
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
INSTALLED_APPS = ['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.staticfiles','library']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','library.middleware.PrivacyMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth']}}]
DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('DATABASE_PATH',str(BASE_DIR / 'private.sqlite3')),'OPTIONS':{'timeout':20}}}
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
PRODUCTION = os.environ.get('PRODUCTION') == '1'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
CSRF_TRUSTED_ORIGINS = list(filter(None,os.environ.get('CSRF_TRUSTED_ORIGINS','').split(',')))
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_000_000
# Keep uploaded PDFs in memory (never spilled to a temp file) for the import parser.
FILE_UPLOAD_MAX_MEMORY_SIZE = 26_214_400
FILE_UPLOAD_HANDLERS = ['django.core.files.uploadhandler.MemoryFileUploadHandler']
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'}]
AI_PROVIDER = os.environ.get('AI_PROVIDER','mock')  # mock | openrouter | gemini | compatible
AI_MODEL = os.environ.get('AI_MODEL','')
AI_API_KEY = os.environ.get('AI_API_KEY','')
AI_BASE_URL = os.environ.get('AI_BASE_URL','')  # optional for openrouter; required for compatible
AI_APP_TITLE = os.environ.get('AI_APP_TITLE','')  # optional OpenRouter attribution
AI_APP_URL = os.environ.get('AI_APP_URL','')
LOGGING = {'version':1,'disable_existing_loggers':False,'handlers':{'null':{'class':'logging.NullHandler'}},'loggers':{'django.request':{'handlers':['null'],'propagate':False},'httpx':{'handlers':['null'],'propagate':False},'pypdf':{'handlers':['null'],'propagate':False}}}

if PRODUCTION:
    if not os.environ.get('DJANGO_SECRET_KEY'):
        raise RuntimeError('Production requires an explicit DJANGO_SECRET_KEY.')
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
