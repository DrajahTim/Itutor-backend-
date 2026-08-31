from rest_framework import serializers

from learning.serializers import QuestionPublicSerializer

from .models import Recommendation, ReviewSchedule, StudentProfile


class StudentProfileSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            "id", "topic", "topic_name", "mastery_level",
            "avg_score", "attempts_count", "last_activity_at",
        ]


class RecommendationSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = Recommendation
        fields = ["id", "topic", "topic_name", "reason", "created_at"]


class ReviewScheduleSerializer(serializers.ModelSerializer):
    # A due review card. Nests QuestionPublicSerializer rather than
    # redefining the field list — that serializer already exists precisely
    # to expose a question WITHOUT correct_option, so reusing it means the
    # answer can't leak here even if Question gains new fields later.
    question_detail = QuestionPublicSerializer(source="question", read_only=True)
    # Denormalised labels so the review UI can show context ("Sorting
    # Algorithms - Week 3 Quiz") without extra round trips, same style as
    # topic_name above.
    topic = serializers.IntegerField(source="question.quiz.topic_id", read_only=True)
    topic_name = serializers.CharField(source="question.quiz.topic.name", read_only=True)
    quiz_title = serializers.CharField(source="question.quiz.title", read_only=True)

    class Meta:
        model = ReviewSchedule
        fields = [
            "id", "question", "question_detail", "topic", "topic_name", "quiz_title",
            "ease_factor", "interval_days", "repetitions",
            "next_review_at", "last_reviewed_at",
        ]


class SubmitReviewSerializer(serializers.Serializer):
    # Input shape for a single review answer. Only the selected option is
    # accepted — correctness is graded server-side against the real
    # Question.correct_option, same rule as SubmitAttemptSerializer.
    selected_option = serializers.ChoiceField(choices=["A", "B", "C", "D"])