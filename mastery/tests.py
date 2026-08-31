from datetime import timedelta

from django.test import TestCase
import pytest
from django.urls import reverse
from django.utils import timezone

from learning.models import Attempt, AttemptAnswer, Quiz, Topic
from mastery.models import Recommendation, ReviewSchedule, StudentProfile
from mastery.signals import (
    EASE_MAX,
    EASE_MIN,
    EASE_START,
    calculate_mastery,
    schedule_review,
)


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


class TestScheduleReview:
    # Pure unit tests for the SM-2 function — no DB, same style as
    # TestMasteryCalculation above. Every scheduling rule is verified
    # here so the DB-backed tests below only have to prove the wiring.
    def test_first_correct_answer_schedules_one_day(self):
        state = schedule_review(EASE_START, 1, 0, is_correct=True)
        assert state["repetitions"] == 1
        assert state["interval_days"] == 1
        assert state["ease_factor"] == 2.6

    def test_second_correct_answer_schedules_six_days(self):
        state = schedule_review(2.6, 1, 1, is_correct=True)
        assert state["repetitions"] == 2
        assert state["interval_days"] == 6
        assert state["ease_factor"] == 2.7

    def test_third_correct_answer_multiplies_by_ease(self):
        # round(6 * 2.7) == 16
        state = schedule_review(2.7, 6, 2, is_correct=True)
        assert state["repetitions"] == 3
        assert state["interval_days"] == 16
        assert state["ease_factor"] == 2.8

    def test_ease_factor_capped_at_max(self):
        state = schedule_review(EASE_MAX, 16, 3, is_correct=True)
        assert state["ease_factor"] == EASE_MAX

    def test_wrong_answer_resets_to_one_day(self):
        state = schedule_review(2.8, 45, 4, is_correct=False)
        assert state["repetitions"] == 0
        assert state["interval_days"] == 1
        assert state["ease_factor"] == 2.6

    def test_ease_factor_floored_at_min(self):
        # Standard SM-2 floor: repeated misses must never push ease below
        # 1.3, or intervals would collapse (or invert) entirely.
        ease = EASE_START
        for _ in range(10):
            ease = schedule_review(ease, 1, 0, is_correct=False)["ease_factor"]
        assert ease == EASE_MIN

    def test_next_review_at_is_now_plus_interval(self):
        now = timezone.now()
        state = schedule_review(2.7, 6, 2, is_correct=True, now=now)
        assert state["next_review_at"] == now + timedelta(days=16)



@pytest.mark.django_db
class TestReviewScheduleAutoUpdate:
    # The signal-wiring tests, mirroring TestProfileAutoUpdate: save an
    # AttemptAnswer and assert the side effect happened, without the test
    # ever calling the scheduling code directly.
    def _answer(self, student, quiz, question, is_correct):
        attempt = Attempt.objects.create(
            student=student, quiz=quiz, score=0, time_spent_seconds=10
        )
        return AttemptAnswer.objects.create(
            attempt=attempt,
            question=question,
            selected_option=question.correct_option if is_correct else "D",
            is_correct=is_correct,
        )

    def test_answering_question_creates_schedule(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        q1 = questions[0]
        assert ReviewSchedule.objects.filter(student=student_user).count() == 0

        self._answer(student_user, quiz, q1, is_correct=True)

        schedule = ReviewSchedule.objects.get(student=student_user, question=q1)
        assert schedule.repetitions == 1
        assert schedule.interval_days == 1
        assert schedule.ease_factor == 2.6
        assert schedule.last_reviewed_at is not None

    def test_interval_grows_on_repeated_correct_answers(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        q1 = questions[0]
        intervals = []
        for _ in range(3):
            self._answer(student_user, quiz, q1, is_correct=True)
            intervals.append(
                ReviewSchedule.objects.get(student=student_user, question=q1).interval_days
            )

        assert intervals == [1, 6, 16]

    def test_wrong_answer_resets_interval_to_one_day(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        q1 = questions[0]
        for _ in range(3):
            self._answer(student_user, quiz, q1, is_correct=True)
        assert ReviewSchedule.objects.get(student=student_user, question=q1).interval_days == 16

        self._answer(student_user, quiz, q1, is_correct=False)

        schedule = ReviewSchedule.objects.get(student=student_user, question=q1)
        assert schedule.interval_days == 1
        assert schedule.repetitions == 0
        assert schedule.ease_factor == 2.6  # 2.8 - 0.2

    def test_schedule_updates_not_duplicates(self, student_user, quiz_with_questions):
        # Confirms unique_together is doing its job — one row per
        # (student, question), same check as the StudentProfile version.
        quiz, questions = quiz_with_questions
        q1 = questions[0]
        for _ in range(4):
            self._answer(student_user, quiz, q1, is_correct=True)

        assert ReviewSchedule.objects.filter(student=student_user, question=q1).count() == 1

    def test_next_review_at_moves_forward_with_interval(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        q1 = questions[0]
        self._answer(student_user, quiz, q1, is_correct=True)
        first = ReviewSchedule.objects.get(student=student_user, question=q1).next_review_at
        self._answer(student_user, quiz, q1, is_correct=True)
        second = ReviewSchedule.objects.get(student=student_user, question=q1).next_review_at

        assert second > first

    def test_each_question_scheduled_independently(self, student_user, quiz_with_questions):
        quiz, questions = quiz_with_questions
        q1, q2 = questions
        self._answer(student_user, quiz, q1, is_correct=True)
        self._answer(student_user, quiz, q2, is_correct=False)

        assert ReviewSchedule.objects.filter(student=student_user).count() == 2
        assert ReviewSchedule.objects.get(question=q1).repetitions == 1
        assert ReviewSchedule.objects.get(question=q2).repetitions == 0

@pytest.mark.django_db
class TestReviewEndpoints:
    def _schedule(self, student, question, due_in_days=-1, **kwargs):
        # due_in_days < 0 means already due; > 0 means not due yet.
        return ReviewSchedule.objects.create(
            student=student,
            question=question,
            next_review_at=timezone.now() + timedelta(days=due_in_days),
            **kwargs,
        )

    def test_due_reviews_requires_auth(self, api_client):
        response = api_client.get(reverse("due-reviews"))
        assert response.status_code == 401

    def test_submit_review_requires_auth(self, api_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        schedule = self._schedule(student_user, questions[0])

        response = api_client.post(
            reverse("submit-review", args=[schedule.id]), {"selected_option": "C"}, format="json"
        )
        assert response.status_code == 401

    def test_due_reviews_returns_only_due_items(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        q1, q2 = questions
        self._schedule(student_user, q1, due_in_days=-1)
        self._schedule(student_user, q2, due_in_days=5)  # not due yet

        response = authenticated_client.get(reverse("due-reviews"))
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["question"] == q1.id

    def test_due_reviews_ordered_soonest_first(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        q1, q2 = questions
        self._schedule(student_user, q1, due_in_days=-1)
        self._schedule(student_user, q2, due_in_days=-9)

        response = authenticated_client.get(reverse("due-reviews"))
        assert [row["question"] for row in response.data] == [q2.id, q1.id]

    def test_due_reviews_never_leaks_correct_option(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        self._schedule(student_user, questions[0])

        response = authenticated_client.get(reverse("due-reviews"))
        row = response.data[0]
        assert "correct_option" not in row
        assert "correct_option" not in row["question_detail"]

    def test_due_reviews_only_returns_own_schedules(self, authenticated_client, student_user, quiz_with_questions, django_user_model):
        _, questions = quiz_with_questions
        other = django_user_model.objects.create_user(
            email="other@example.com", username="other", full_name="Other",
            password="TestPass123!", role="student",
        )
        self._schedule(other, questions[0])

        response = authenticated_client.get(reverse("due-reviews"))
        assert list(response.data) == []

    def test_submit_correct_review_advances_schedule(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        q1 = questions[0]  # correct_option == "C"
        schedule = self._schedule(student_user, q1)

        response = authenticated_client.post(
            reverse("submit-review", args=[schedule.id]), {"selected_option": "C"}, format="json"
        )
        assert response.status_code == 200
        assert response.data["is_correct"] is True
        assert response.data["correct_option"] == "C"
        assert response.data["schedule"]["repetitions"] == 1
        assert response.data["schedule"]["interval_days"] == 1

        schedule.refresh_from_db()
        assert schedule.repetitions == 1
        assert schedule.ease_factor == 2.6
        assert schedule.last_reviewed_at is not None

    def test_submit_wrong_review_resets_schedule(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        schedule = self._schedule(
            student_user, questions[0], ease_factor=2.8, interval_days=16, repetitions=3
        )

        response = authenticated_client.post(
            reverse("submit-review", args=[schedule.id]), {"selected_option": "A"}, format="json"
        )
        assert response.status_code == 200
        assert response.data["is_correct"] is False

        schedule.refresh_from_db()
        assert schedule.repetitions == 0
        assert schedule.interval_days == 1
        assert schedule.ease_factor == 2.6

    def test_submit_review_does_not_duplicate_schedule(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        schedule = self._schedule(student_user, questions[0])

        for _ in range(2):
            authenticated_client.post(
                reverse("submit-review", args=[schedule.id]),
                {"selected_option": "C"}, format="json",
            )

        assert ReviewSchedule.objects.filter(student=student_user).count() == 1

    def test_submit_someone_elses_review_404s(self, authenticated_client, quiz_with_questions, django_user_model):
        # 404 rather than 403 — the privacy convention used throughout, so
        # probing an id can never confirm that the row exists.
        _, questions = quiz_with_questions
        other = django_user_model.objects.create_user(
            email="other@example.com", username="other", full_name="Other",
            password="TestPass123!", role="student",
        )
        schedule = self._schedule(other, questions[0])

        response = authenticated_client.post(
            reverse("submit-review", args=[schedule.id]), {"selected_option": "C"}, format="json"
        )
        assert response.status_code == 404

    def test_submit_review_rejects_invalid_option(self, authenticated_client, student_user, quiz_with_questions):
        _, questions = quiz_with_questions
        schedule = self._schedule(student_user, questions[0])

        response = authenticated_client.post(
            reverse("submit-review", args=[schedule.id]), {"selected_option": "Z"}, format="json"
        )
        assert response.status_code == 400

    def test_submit_review_grades_server_side(self, authenticated_client, student_user, quiz_with_questions):
        # A client-supplied is_correct flag must be ignored entirely —
        # same rule SubmitAttemptView enforces for scores.
        _, questions = quiz_with_questions
        schedule = self._schedule(student_user, questions[0])

        response = authenticated_client.post(
            reverse("submit-review", args=[schedule.id]),
            {"selected_option": "A", "is_correct": True}, format="json",
        )
        assert response.data["is_correct"] is False



