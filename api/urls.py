from django.urls import path

from api import views

urlpatterns = [
    path("funds/<uuid:fund_id>/accounts/", views.FundAccountsView.as_view()),
    path("funds/<uuid:fund_id>/capital-calls/", views.CapitalCallsView.as_view()),
    path("accounts/<uuid:account_id>/balance/", views.AccountBalanceView.as_view()),
    path("accounts/<uuid:account_id>/entries/", views.AccountEntriesView.as_view()),
    path("funds/<uuid:fund_id>/distributions/", views.DistributionsView.as_view()),
    path("transfers/<uuid:transfer_id>/reverse/", views.ReverseTransferView.as_view()),
    path("funds/<uuid:fund_id>/lps/<uuid:lp_id>/statement/", views.LPStatementView.as_view()),
    path("funds/<uuid:fund_id>/reconciliation/", views.FundReconciliationView.as_view()),
    path("funds/<uuid:fund_id>/periods/", views.FundPeriodsView.as_view()),
    path("funds/<uuid:fund_id>/periods/<uuid:period_id>/close/", views.ClosePeriodView.as_view()),
    path("me/", views.MeView.as_view()),
]
