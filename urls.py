from django.urls import path
from app import views
urlpatterns=[path("",views.home),path("queue/",views.queue_pdfs),path("start/",views.start),path("stop/",views.stop),path("status/",views.status),path("export/",views.export_csv)]
