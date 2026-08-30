from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Attempt, AttemptAnswer, Lesson, Question, Quiz, Topic, Course
from .permissions import IsAdminOrReadOnly, IsOwnerOrAdminOrReadOnly
from .serializers import (
    AttemptSerializer,
    CourseSerializer,
    GenerateQuizSerializer,
    LessonSerializer,
    QuestionAdminSerializer,
    QuizDetailSerializer,
    QuizSerializer,
    SubmitAttemptSerializer,
    TopicSerializer,
    CourseDetailSerializer,
)


class TopicViewSet(viewsets.ModelViewSet):
    serializer_class = TopicSerializer
    permission_classes = [IsOwnerOrAdminOrReadOnly]

    def get_queryset(self):
        # A student sees every curated topic (owner is null) PLUS their
        # own private topics — never another student's private topics.
        user = self.request.user
        return Topic.objects.filter(
            models.Q(owner__isnull=True) | models.Q(owner=user)
        )

    def perform_create(self, serializer):
        # Same rule as CourseViewSet — admin-created topics are
        # curated (owner=None, visible to all students); student-
        # created topics are private to them.
        owner = None if self.request.user.role == "admin" else self.request.user
        serializer.save(owner=owner)


class LessonViewSet(viewsets.ModelViewSet):
    serializer_class = LessonSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        # Only lessons under topics this user can actually see (curated
        # topics + their own private ones) — mirrors TopicViewSet's
        # visibility rule so a lesson never leaks from someone else's
        # private topic just because its ID is guessed.
        user = self.request.user
        queryset = Lesson.objects.filter(
            models.Q(topic__owner__isnull=True) | models.Q(topic__owner=user)
        )
        topic_id = self.request.query_params.get("topic")
        if topic_id:
            queryset = queryset.filter(topic_id=topic_id)
        return queryset


class QuizViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        # Same visibility rule as LessonViewSet — a quiz generated under
        # a private topic must stay private to its owner.
        user = self.request.user
        queryset = Quiz.objects.filter(
            models.Q(topic__owner__isnull=True) | models.Q(topic__owner=user)
        )
        topic_id = self.request.query_params.get("topic")
        if topic_id:
            queryset = queryset.filter(topic_id=topic_id)
        return queryset

    def get_serializer_class(self):
        # /quizzes/<id>/ (retrieve) includes the questions for taking
        # the quiz. /quizzes/ (list) doesn't, to keep the list light.
        if self.action == "retrieve":
            return QuizDetailSerializer
        return QuizSerializer


class QuestionViewSet(viewsets.ModelViewSet):
    # Admin-only in practice (write always requires admin via the
    # permission class; a plain student would never hit this directly
    # since quiz-taking goes through QuizDetailSerializer's public
    # question serializer instead).
    serializer_class = QuestionAdminSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = Question.objects.all()
        quiz_id = self.request.query_params.get("quiz")
        if quiz_id:
            queryset = queryset.filter(quiz_id=quiz_id)
        return queryset


class SubmitAttemptView(APIView):
    # POST /api/learning/quizzes/<quiz_id>/submit/
    # Grades the submission server-side — the score is never trusted
    # from the client, only the selected options are.
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        serializer = SubmitAttemptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        attempt = Attempt.objects.create(
            student=request.user,
            quiz=quiz,
            score=0,  # placeholder, updated below once graded
            time_spent_seconds=data["time_spent_seconds"],
        )

        correct_count = 0
        total = len(data["answers"])

        for answer in data["answers"]:
            question = get_object_or_404(
                Question, id=answer["question_id"], quiz=quiz
            )
            is_correct = answer["selected_option"] == question.correct_option
            if is_correct:
                correct_count += 1

            AttemptAnswer.objects.create(
                attempt=attempt,
                question=question,
                selected_option=answer["selected_option"],
                is_correct=is_correct,
            )

        score = (correct_count / total * 100) if total > 0 else 0
        attempt.score = round(score, 2)
        attempt.save()

        return Response(AttemptSerializer(attempt).data, status=201)


class MyAttemptsView(generics.ListAPIView):
    # GET /api/learning/attempts/mine/ — a student's own quiz history.
    serializer_class = AttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Attempt.objects.filter(student=self.request.user).order_by("-submitted_at")

class GenerateQuizView(APIView):
    # POST /api/learning/quizzes/generate/
    # Generates a quiz from a document the requesting user can access
    # (their own upload, or a curated one), using the LLM.
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from chatbot.models import CourseDocument
        from chatbot.quiz_generation import QuizGenerationError, generate_quiz_from_document

        serializer = GenerateQuizSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # get_object_or_404 combined with this queryset means a document
        # that exists but isn't visible to this user (someone else's
        # private upload) 404s instead of 403 — same privacy reasoning
        # as TopicViewSet's object-level filtering.
        document = get_object_or_404(
            CourseDocument.objects.filter(
                models.Q(owner__isnull=True) | models.Q(owner=request.user)
            ),
            id=data["document_id"],
        )

        try:
            quiz = generate_quiz_from_document(document, num_questions=data["num_questions"])
        except QuizGenerationError as e:
            return Response({"detail": str(e)}, status=422)

        return Response(QuizDetailSerializer(quiz).data, status=201)

class CourseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwnerOrAdminOrReadOnly]

    def get_queryset(self):
        # Same visibility rule as Topic: curated courses (owner=None)
        # plus the requesting user's own private ones.
        user = self.request.user
        return Course.objects.filter(
            models.Q(owner__isnull=True) | models.Q(owner=user)
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CourseDetailSerializer
        return CourseSerializer

    def perform_create(self, serializer):
        # Admins curate shared courses (owner=None, visible to
        # everyone); a student's own course is private to them —
        # same rule already used for CourseDocument uploads.
        owner = None if self.request.user.role == "admin" else self.request.user
        serializer.save(owner=owner)

    @action(detail=True, methods=["get"], url_path="progress")
    def progress(self, request, pk=None):
        # GET /api/learning/courses/<id>/progress/
        # Rolls the student's existing per-topic mastery (maintained by
        # the mastery app's signal on every Attempt) up to the course
        # level: how much of the syllabus they've studied, their overall
        # standing, and their strongest/weakest topics — the data the
        # course dashboard and "recommend next steps" are built on.
        #
        # Imported here (not at module top) to keep the learning app
        # from importing the mastery app at load time — same lazy
        # cross-app import style GenerateQuizView uses for chatbot.
        from mastery.models import Recommendation, StudentProfile
        from mastery.serializers import RecommendationSerializer
        from mastery.signals import calculate_mastery

        # get_object() runs through get_queryset()'s visibility filter,
        # so another user's private course correctly 404s here.
        course = self.get_object()
        student = request.user

        topics = list(course.topics.all())
        # This student's mastery rows for topics in THIS course, keyed by
        # topic id for O(1) lookup while building the per-topic list.
        profiles = {
            profile.topic_id: profile
            for profile in StudentProfile.objects.filter(
                student=student, topic__course=course
            )
        }

        topic_rows = []
        studied_scores = []
        for topic in topics:
            profile = profiles.get(topic.id)
            studied = profile is not None
            topic_rows.append({
                "id": topic.id,
                "name": topic.name,
                "order": topic.order,
                "studied": studied,
                # A brand-new student who hasn't attempted a topic is
                # "not started" (null), deliberately NOT mislabeled
                # "weak" — weak means "tried and scored low".
                "mastery_level": profile.mastery_level if studied else None,
                "avg_score": profile.avg_score if studied else None,
                "attempts_count": profile.attempts_count if studied else 0,
            })
            if studied:
                studied_scores.append(profile.avg_score)

        topics_total = len(topics)
        topics_studied = len(studied_scores)
        completion_percent = (
            round(topics_studied / topics_total * 100, 2) if topics_total else 0.0
        )

        # Overall standing is the mean of the studied topics' averages —
        # unstudied topics are excluded so they don't drag a good
        # student down to "weak". calculate_mastery is reused verbatim
        # so course-level and topic-level mastery never diverge.
        if topics_studied:
            average_score = round(sum(studied_scores) / topics_studied, 2)
            mastery_level = calculate_mastery(average_score)
        else:
            average_score = None
            mastery_level = None

        studied_rows = [row for row in topic_rows if row["studied"]]
        strongest = max(studied_rows, key=lambda r: r["avg_score"], default=None)
        weakest = min(studied_rows, key=lambda r: r["avg_score"], default=None)

        def summarize(row):
            if not row:
                return None
            return {
                "id": row["id"],
                "name": row["name"],
                "avg_score": row["avg_score"],
                "mastery_level": row["mastery_level"],
            }

        recommendations = Recommendation.objects.filter(
            student=student, topic__course=course
        )

        return Response({
            "course": {"id": course.id, "name": course.name, "code": course.code},
            "topics_total": topics_total,
            "topics_studied": topics_studied,
            "completion_percent": completion_percent,
            "average_score": average_score,
            "mastery_level": mastery_level,
            "strongest_topic": summarize(strongest),
            "weakest_topic": summarize(weakest),
            "topics": topic_rows,
            "recommendations": RecommendationSerializer(recommendations, many=True).data,
        })
