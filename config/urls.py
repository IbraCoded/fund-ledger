from django.urls import path

from observability.views import healthz

urlpatterns = [
    path("healthz", healthz),
]
