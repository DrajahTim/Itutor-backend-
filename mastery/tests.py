from django.test import TestCase
import pytest
from django.urls import reverse

from learning.models import Attempt, AttemptAnswer, Quiz, Topic
from mastery.models import Recommendation, StudentProfile
from mastery.signals import calculate_mastery


class TestMasteryCalculation:
    # Pure unit tests, no DB needed — just testing the threshold logic
    # in isolation, matching the rule we agreed on: <50 weak, 50-75
    # average, >75 strong.
    def test_below_50_is_weak(self):
        assert calculate_mastery(0) == "weak"
        assert calculate_mastery(49.9) == "weak"

    def test_50_to_75_is_average(self):
        assert calculate_mastery(50) == "average"
        assert calculate_mastery(74.9) == "average"

    def test_above_75_is_strong(self):
        assert calculate_mastery(75) == "strong"
        assert calculate_mastery(100) == "strong"


@pytest.mark.django_db
class TestProfileAutoUpdate:
    def test_submitting_attempt_creates_profile(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        assert StudentProfile.objects.filter(student=student_user, topic=quiz.topic).count() == 0

        Attempt.objects.create(student=student_user, quiz=quiz, score=80, time_spent_seconds=30)

        profile = StudentProfile.objects.get(student=student_user, topic=quiz.topic)
        assert profile.avg_score == 80
        assert profile.mastery_level == "strong"
        assert profile.attempts_count == 1

    def test_profile_averages_across_multiple_attempts(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        Attempt.objects.create(student=student_user, quiz=quiz, score=100, time_spent_seconds=30)
        Attempt.objects.create(student=student_user, quiz=quiz, score=0, time_spent_seconds=30)

        profile = StudentProfile.objects.get(student=student_user, topic=quiz.topic)
        assert profile.avg_score == 50.0
        assert profile.attempts_count == 2
        assert profile.mastery_level == "average"  # exactly 50 -> average, not weak

    def test_weak_mastery_creates_recommendation(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        assert Recommendation.objects.filter(student=student_user).count() == 0

        Attempt.objects.create(student=student_user, quiz=quiz, score=20, time_spent_seconds=30)

        assert Recommendation.objects.filter(student=student_user, topic=quiz.topic).count() == 1

    def test_strong_mastery_does_not_create_recommendation(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        Attempt.objects.create(student=student_user, quiz=quiz, score=90, time_spent_seconds=30)

        assert Recommendation.objects.filter(student=student_user, topic=quiz.topic).count() == 0

    def test_profile_updates_not_duplicates_on_second_attempt(self, student_user, quiz_with_questions):
        # Confirms unique_together is actually doing its job — one row
        # per (student, topic), updated in place, never duplicated.
        quiz, questions = quiz_with_questions
        Attempt.objects.create(student=student_user, quiz=quiz, score=80, time_spent_seconds=30)
        Attempt.objects.create(student=student_user, quiz=quiz, score=60, time_spent_seconds=30)

        assert StudentProfile.objects.filter(student=student_user, topic=quiz.topic).count() == 1


@pytest.mark.django_db
class TestMasteryEndpoints:
    def test_my_profiles_requires_auth(self, api_client):
        response = api_client.get(reverse("my-profiles"))
        assert response.status_code == 401

    def test_my_profiles_returns_own_data(self, authenticated_client, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        Attempt.objects.create(student=student_user, quiz=quiz, score=80, time_spent_seconds=30)

        response = authenticated_client.get(reverse("my-profiles"))
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["mastery_level"] == "strong"


@pytest.mark.django_db
class TestAnalyticsOverview:
    def test_requires_auth(self, api_client):
        response = api_client.get(reverse("analytics-overview"))
        assert response.status_code == 401

    def test_empty_when_no_attempts(self, authenticated_client):
        # A brand-new student gets a well-formed, empty payload — no
        # nulls-as-crashes, and average_score is None (not 0) because
        # "no data" and "scored zero" are different truths.
        response = authenticated_client.get(reverse("analytics-overview"))
        assert response.status_code == 200
        assert response.data["summary"]["total_attempts"] == 0
        assert response.data["summary"]["topics_studied"] == 0
        assert response.data["summary"]["average_score"] is None
        assert response.data["summary"]["mastery_level"] is None
        assert response.data["topics"] == []
        assert response.data["score_trend"] == []
        assert response.data["most_missed"] == []

    def test_summary_uses_studied_only_average(self, authenticated_client, student_user, quiz_with_questions):
        # One topic scored 100, another 40 -> studied-only mean is 70
        # (average band), matching the dashboard's definition exactly.
        quiz, _ = quiz_with_questions
        Attempt.objects.create(student=student_user, quiz=quiz, score=100, time_spent_seconds=30)

        other_topic = Topic.objects.create(name="Graphs", slug="graphs", order=2)
        other_quiz = Quiz.objects.create(topic=other_topic, title="Graphs Quiz", passing_score=60)
        Attempt.objects.create(student=student_user, quiz=other_quiz, score=40, time_spent_seconds=50)

        response = authenticated_client.get(reverse("analytics-overview"))
        assert response.status_code == 200
        summary = response.data["summary"]
        assert summary["topics_studied"] == 2
        assert summary["average_score"] == 70.0
        assert summary["mastery_level"] == "average"
        assert summary["total_time_seconds"] == 80
        assert summary["distribution"] == {"weak": 1, "average": 0, "strong": 1}

    def test_topics_table_sorted_weakest_first_with_best_score(self, authenticated_client, student_user, quiz_with_questions):
        quiz, _ = quiz_with_questions
        # Two attempts on the same topic: avg 60, best 80.
        Attempt.objects.create(student=student_user, quiz=quiz, score=40, time_spent_seconds=10)
        Attempt.objects.create(student=student_user, quiz=quiz, score=80, time_spent_seconds=20)

        weak_topic = Topic.objects.create(name="Recursion", slug="recursion", order=3)
        weak_quiz = Quiz.objects.create(topic=weak_topic, title="Recursion Quiz", passing_score=60)
        Attempt.objects.create(student=student_user, quiz=weak_quiz, score=20, time_spent_seconds=15)

        response = authenticated_client.get(reverse("analytics-overview"))
        rows = response.data["topics"]
        assert [r["topic_name"] for r in rows] == ["Recursion", "Sorting Algorithms"]
        sorting = rows[1]
        assert sorting["avg_score"] == 60.0
        assert sorting["best_score"] == 80.0
        assert sorting["attempts_count"] == 2
        assert sorting["total_time_seconds"] == 30

    def test_score_trend_is_chronological(self, authenticated_client, student_user, quiz_with_questions):
        quiz, _ = quiz_with_questions
        Attempt.objects.create(student=student_user, quiz=quiz, score=30, time_spent_seconds=10)
        Attempt.objects.create(student=student_user, quiz=quiz, score=90, time_spent_seconds=10)

        response = authenticated_client.get(reverse("analytics-overview"))
        trend = response.data["score_trend"]
        assert [point["score"] for point in trend] == [30.0, 90.0]

    def test_most_missed_ranks_worst_questions_first(self, authenticated_client, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        q1, q2 = questions
        attempt = Attempt.objects.create(student=student_user, quiz=quiz, score=50, time_spent_seconds=10)
        # q1 missed once, q2 missed twice -> q2 should rank first.
        AttemptAnswer.objects.create(attempt=attempt, question=q1, selected_option="A", is_correct=False)
        AttemptAnswer.objects.create(attempt=attempt, question=q2, selected_option="B", is_correct=False)
        attempt2 = Attempt.objects.create(student=student_user, quiz=quiz, score=50, time_spent_seconds=10)
        AttemptAnswer.objects.create(attempt=attempt2, question=q1, selected_option="C", is_correct=True)
        AttemptAnswer.objects.create(attempt=attempt2, question=q2, selected_option="B", is_correct=False)

        response = authenticated_client.get(reverse("analytics-overview"))
        missed = response.data["most_missed"]
        assert len(missed) == 2
        assert missed[0]["question_id"] == q2.id
        assert missed[0]["misses"] == 2
        assert missed[0]["answered"] == 2
        assert missed[0]["miss_rate"] == 100.0
        assert missed[1]["question_id"] == q1.id
        assert missed[1]["miss_rate"] == 50.0

    def test_only_returns_own_data(self, authenticated_client, student_user, quiz_with_questions, django_user_model):
        quiz, _ = quiz_with_questions
        other = django_user_model.objects.create_user(
            email="other@example.com", username="other", full_name="Other",
            password="TestPass123!", role="student",
        )
        Attempt.objects.create(student=other, quiz=quiz, score=90, time_spent_seconds=10)

        response = authenticated_client.get(reverse("analytics-overview"))
        assert response.data["summary"]["total_attempts"] == 0
        assert response.data["topics"] == []


