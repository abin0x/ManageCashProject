"""Project-level URL configuration for Mahmudul_Hasan_Abin_1554_ManageCash."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('ManageCash.urls')),
]
