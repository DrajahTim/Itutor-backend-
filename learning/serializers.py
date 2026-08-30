from rest_framework import serializers

from .models import Attempt, AttemptAnswer, Lesson, Question, Quiz, Topic, Course


class TopicSerializer(serializers.ModelSerializer):
    # is_mine lets the frontend distinguish curated vs the student's own
    # topics without extra client-side logic — just a computed flag.
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        # `course` is writable so a topic can be attached to a course on
        # creation (e.g. from the course page). Without it here, DRF would
        # silently drop the `course` value sent by the client.
        fields = ["id", "name", "slug", "description", "order", "owner", "course", "is_mine"]
        # owner is set automatically from the request, never trusted
        # from client input (same "read_only + force it" pattern used
        # for role in RegisterSerializer).
        read_only_fields = ["owner"]

    def get_is_mine(self, obj):
        request = self.context.get("request")
        return bool(request and obj.owner_id == request.user.id)

class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "topic", "title", "content", "order", "created_at"]


class QuestionAdminSerializer(serializers.ModelSerializer):
    # Full serializer, including the correct answer — only ever used
    # behind the IsAdminOrReadOnly permission.
    class Meta:
        model = Question
        fields = [
            "id", "quiz", "text", "option_a", "option_b",
            "option_c", "option_d", "correct_option",
        ]


class QuestionPublicSerializer(serializers.ModelSerializer):
    # What a student sees when taking a quiz — deliberately excludes
    # correct_option so the answer can't be read straight from the API.
    class Meta:
        model = Question
        fields = ["id", "quiz", "text", "option_a", "option_b", "option_c", "option_d"]


class QuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        fields = ["id", "topic", "title", "passing_score", "created_at"]


class QuizDetailSerializer(serializers.ModelSerializer):
    # Quiz + its questions, for when a student starts taking it.
    questions = QuestionPublicSerializer(many=True, read_only=True)

    class Meta:
        model = Quiz
        fields = ["id", "topic", "title", "passing_score", "questions"]


class QuestionResultSerializer(serializers.ModelSerializer):
    # The FULL question — including the correct answer and explanation.
    # Only ever nested inside an AttemptAnswer (i.e. returned AFTER a
    # quiz is submitted and graded), so unlike QuestionPublicSerializer
    # it's safe to reveal correct_option here.
    class Meta:
        model = Question
        fields = [
            "id", "text", "option_a", "option_b", "option_c",
            "option_d", "correct_option", "explanation",
        ]


class AttemptAnswerSerializer(serializers.ModelSerializer):
    # Nest the full question detail so the results screen can render a
    # per-question breakdown (your answer vs. the correct one, plus the
    # explanation) without a second round-trip to fetch each question.
    question_detail = QuestionResultSerializer(source="question", read_only=True)

    class Meta:
        model = AttemptAnswer
        fields = ["id", "question", "question_detail", "selected_option", "is_correct"]


class AttemptSerializer(serializers.ModelSerializer):
    answers = AttemptAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = Attempt
        fields = [
            "id", "student", "quiz", "score",
            "time_spent_seconds", "submitted_at", "answers",
        ]
        read_only_fields = ["student", "score", "submitted_at"]


class SubmitAnswerInputSerializer(serializers.Serializer):
    # Input shape for one answer in a quiz submission — not tied to a
    # model, just used to validate the incoming request body.
    question_id = serializers.IntegerField()
    selected_option = serializers.ChoiceField(choices=["A", "B", "C", "D"])


class SubmitAttemptSerializer(serializers.Serializer):
    # What the frontend POSTs when a student finishes a quiz.
    time_spent_seconds = serializers.IntegerField(default=0)
    answers = SubmitAnswerInputSerializer(many=True)

class GenerateQuizSerializer(serializers.Serializer):
    # What the frontend sends to request a quiz generated from a document.
    document_id = serializers.IntegerField()
    num_questions = serializers.IntegerField(default=5, min_value=1, max_value=15)

class CourseSerializer(serializers.ModelSerializer):
    is_mine = serializers.SerializerMethodField()
    # How many topics this course groups — cheap, useful summary for a
    # course list/card in the frontend without a separate API call.
    topic_count = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            "id", "name", "code", "slug", "description",
            "order", "owner", "is_mine", "topic_count",
        ]
        read_only_fields = ["owner"]

    def get_is_mine(self, obj):
        request = self.context.get("request")
        return bool(request and obj.owner_id == request.user.id)

    def get_topic_count(self, obj):
        return obj.topics.count()


class CourseDetailSerializer(CourseSerializer):
    # Used for the retrieve view — includes the actual topics, not just
    # a count, so the frontend can render a course page in one request.
    topics = TopicSerializer(many=True, read_only=True)

    class Meta(CourseSerializer.Meta):
        fields = CourseSerializer.Meta.fields + ["topics"]