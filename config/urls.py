from django.urls import path
from django.contrib.auth import views as auth
from django.contrib.staticfiles.views import serve
from library import views
urlpatterns=[path('',views.index),path('login/',auth.LoginView.as_view()),path('logout/',auth.LogoutView.as_view()),path('password/',auth.PasswordChangeView.as_view(template_name='registration/password.html',success_url='/')),path('api/templates/',views.templates),path('api/templates/<int:pk>/',views.detail),path('api/templates/<int:pk>/restore/',views.restore),path('api/propose/',views.proposal),path('api/approve/',views.approve),path('api/export/',views.export_data),path('api/import/',views.import_data),path('api/import/pdf/',views.import_pdf),path('api/status/',views.status)]
from django.conf import settings
if not settings.PRODUCTION:
    urlpatterns += [path('static/<path:path>',serve,{'insecure':True})]
