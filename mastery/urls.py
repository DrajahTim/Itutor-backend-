from django.urls import path

from .views import (
    AnalyticsOverviewView,
    DueReviewsView,
    MyProfilesView,
    MyRecommendationsView,
    SubmitReviewView,
)

urlpatterns = [
    path("profiles/mine/", MyProfilesView.as_view(), name="my-profiles"),
    path("recommendations/mine/", MyRecommendationsView.as_view(), name="my-recommendations"),
    path("analytics/overview/", AnalyticsOverviewView.as_view(), name="analytics-overview"),
    path("reviews/due/", DueReviewsView.as_view(), name="due-reviews"),
    path("reviews/<int:schedule_id>/submit/", SubmitReviewView.as_view(), name="submit-review"),
]
