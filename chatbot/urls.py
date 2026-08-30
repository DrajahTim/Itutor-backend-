from django.urls import path

from .views import AskChatbotView, CourseDocumentViewSet, MyChatHistoryView

urlpatterns = [
    path("ask/", AskChatbotView.as_view(), name="ask-chatbot"),
    path("history/", MyChatHistoryView.as_view(), name="chat-history"),
    path("documents/", CourseDocumentViewSet.as_view(), name="course-documents"),
]