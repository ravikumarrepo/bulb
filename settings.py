from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent
SECRET_KEY="local-development-only"
DEBUG=True
ALLOWED_HOSTS=["127.0.0.1","localhost"]
ROOT_URLCONF="urls"
INSTALLED_APPS=["django.contrib.staticfiles","app"]
MIDDLEWARE=["django.middleware.security.SecurityMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware"]
TEMPLATES=[{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[BASE_DIR/"templates"],"APP_DIRS":True,"OPTIONS":{"context_processors":["django.template.context_processors.request"]}}]
STATIC_URL="/static/"
STATICFILES_DIRS=[BASE_DIR/"static"]
DEFAULT_AUTO_FIELD="django.db.models.BigAutoField"
UPLOAD_DIR=BASE_DIR/"data"/"pdfs"
UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
