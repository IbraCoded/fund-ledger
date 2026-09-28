from django.urls import include, path

from observability.views import healthz, metrics

urlpatterns = [
    path("healthz", healthz),
    path("api/v1/", include("api.urls")),
    path("metrics", metrics),
]
