from django.urls import path

from api import views

urlpatterns = [
    path("funds/<uuid:fund_id>/accounts/", views.FundAccountsView.as_view()),
    path("funds/<uuid:fund_id>/capital-calls/", views.CapitalCallsView.as_view()),
    path("accounts/<uuid:account_id>/balance/", views.AccountBalanceView.as_view()),
    path("accounts/<uuid:account_id>/entries/", views.AccountEntriesView.as_view()),
    path("funds/<uuid:fund_id>/distributions/", views.DistributionsView.as_view()),
    path("transfers/<uuid:transfer_id>/reverse/", views.ReverseTransferView.as_view()),
]
