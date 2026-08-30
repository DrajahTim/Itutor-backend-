from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    GenerateQuizView,
    LessonViewSet,
    MyAttemptsView,
    QuestionViewSet,
    QuizViewSet,
    SubmitAttemptView,
    TopicViewSet,
    CourseViewSet,
)

router = DefaultRouter()
router.register(r"topics", TopicViewSet, basename="topic")
router.register(r"lessons", LessonViewSet, basename="lesson")
router.register(r"quizzes", QuizViewSet, basename="quiz")
router.register(r"questions", QuestionViewSet, basename="question")
router.register(r"courses", CourseViewSet, basename="course")

urlpatterns = [
    # These MUST come before the router include — otherwise the router's
    # /quizzes/<pk>/ pattern greedily matches "generate" as if it were
    # a quiz ID, since Django checks patterns top to bottom.
    path("quizzes/<int:quiz_id>/submit/", SubmitAttemptView.as_view(), name="submit-attempt"),
    path("quizzes/generate/", GenerateQuizView.as_view(), name="generate-quiz"),
    path("attempts/mine/", MyAttemptsView.as_view(), name="my-attempts"),
    path("", include(router.urls)),
]