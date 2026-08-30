from django.urls import path

from .views import AnalyticsOverviewView, MyProfilesView, MyRecommendationsView

urlpatterns = [
    path("profiles/mine/", MyProfilesView.as_view(), name="my-profiles"),
    path("recommendations/mine/", MyRecommendationsView.as_view(), name="my-recommendations"),
    path("analytics/overview/", AnalyticsOverviewView.as_view(), name="analytics-overview"),
]
