from django.urls import include, path

from observability.views import healthz

urlpatterns = [
    path("healthz", healthz),
    path("api/v1/", include("api.urls")),
]
