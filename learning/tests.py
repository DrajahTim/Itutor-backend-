from django.test import TestCase
import pytest
from django.urls import reverse

from learning.models import Attempt, Course, Quiz, Topic
from mastery.models import Recommendation


@pytest.mark.django_db
class TestTopicPermissions:
    def test_student_can_list_topics(self, authenticated_client, topic):
        response = authenticated_client.get(reverse("topic-list"))
        assert response.status_code == 200

    def test_student_can_create_own_topic(self, authenticated_client, student_user):
        # Students can now create their own private topics.
        response = authenticated_client.post(
            reverse("topic-list"),
            {"name": "My Custom Topic", "order": 1},
        )
        assert response.status_code == 201
        # owner is forced server-side to the requesting user, never
        # trusted from the request body.
        assert response.data["owner"] == student_user.id
        assert response.data["is_mine"] is True

    def test_student_cannot_edit_another_students_topic(self, api_client, django_user_model, topic):
        owner = django_user_model.objects.create_user(
            email="owner@example.com", username="owner", full_name="Owner",
            password="pass1234", role="student",
        )
        other = django_user_model.objects.create_user(
            email="other@example.com", username="other", full_name="Other",
            password="pass1234", role="student",
        )

        api_client.force_authenticate(user=owner)
        create_response = api_client.post(reverse("topic-list"), {"name": "Owner's Topic"})
        topic_id = create_response.data["id"]

        api_client.force_authenticate(user=other)
        edit_response = api_client.patch(reverse("topic-detail", args=[topic_id]), {"name": "Hijacked"})
        assert edit_response.status_code == 404

    def test_student_does_not_see_others_private_topics(self, api_client, django_user_model):
        owner = django_user_model.objects.create_user(
            email="owner2@example.com", username="owner2", full_name="Owner2",
            password="pass1234", role="student",
        )
        other = django_user_model.objects.create_user(
            email="other2@example.com", username="other2", full_name="Other2",
            password="pass1234", role="student",
        )

        api_client.force_authenticate(user=owner)
        api_client.post(reverse("topic-list"), {"name": "Private Topic"})

        api_client.force_authenticate(user=other)
        response = api_client.get(reverse("topic-list"))
        names = [t["name"] for t in response.data]
        assert "Private Topic" not in names

    def test_admin_can_create_topic(self, admin_client):
        response = admin_client.post(
            reverse("topic-list"),
            {"name": "New Topic", "slug": "new-topic", "order": 1},
        )
        assert response.status_code == 201

    def test_unauthenticated_user_cannot_access_topics(self, api_client):
        response = api_client.get(reverse("topic-list"))
        assert response.status_code == 401


@pytest.mark.django_db
class TestQuizDetail:
    def test_quiz_detail_hides_correct_option(self, authenticated_client, quiz_with_questions):
        # This is the core anti-cheating guarantee: a student taking a
        # quiz must never see correct_option in the API response.
        quiz, questions = quiz_with_questions
        response = authenticated_client.get(reverse("quiz-detail", args=[quiz.id]))
        assert response.status_code == 200
        for question_data in response.data["questions"]:
            assert "correct_option" not in question_data


@pytest.mark.django_db
class TestQuizSubmission:
    def test_grading_computes_correct_score(self, authenticated_client, quiz_with_questions):
        # The most important test in the whole suite: grading must be
        # computed server-side and must be mathematically correct.
        quiz, questions = quiz_with_questions
        response = authenticated_client.post(
            reverse("submit-attempt", args=[quiz.id]),
            {
                "time_spent_seconds": 30,
                "answers": [
                    {"question_id": questions[0].id, "selected_option": "C"},  # correct
                    {"question_id": questions[1].id, "selected_option": "A"},  # correct
                ],
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["score"] == 100.0

    def test_grading_handles_partial_correctness(self, authenticated_client, quiz_with_questions):
        quiz, questions = quiz_with_questions
        response = authenticated_client.post(
            reverse("submit-attempt", args=[quiz.id]),
            {
                "time_spent_seconds": 30,
                "answers": [
                    {"question_id": questions[0].id, "selected_option": "C"},  # correct
                    {"question_id": questions[1].id, "selected_option": "B"},  # wrong
                ],
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["score"] == 50.0

    def test_score_cannot_be_supplied_by_client(self, authenticated_client, quiz_with_questions):
        # Confirms grading can't be spoofed — even if a "score" field is
        # smuggled into the request body, the server-computed value wins.
        quiz, questions = quiz_with_questions
        response = authenticated_client.post(
            reverse("submit-attempt", args=[quiz.id]),
            {
                "score": 100,  # attempted spoof
                "time_spent_seconds": 30,
                "answers": [
                    {"question_id": questions[0].id, "selected_option": "D"},  # wrong
                    {"question_id": questions[1].id, "selected_option": "B"},  # wrong
                ],
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["score"] == 0.0

    def test_my_attempts_only_shows_own_attempts(self, api_client, django_user_model, quiz_with_questions):
        quiz, questions = quiz_with_questions
        student_a = django_user_model.objects.create_user(
            email="a@example.com", username="a", full_name="A", password="pass1234", role="student"
        )
        student_b = django_user_model.objects.create_user(
            email="b@example.com", username="b", full_name="B", password="pass1234", role="student"
        )

        api_client.force_authenticate(user=student_a)
        api_client.post(
            reverse("submit-attempt", args=[quiz.id]),
            {"time_spent_seconds": 10, "answers": [{"question_id": questions[0].id, "selected_option": "C"}]},
            format="json",
        )

        api_client.force_authenticate(user=student_b)
        response = api_client.get(reverse("my-attempts"))
        assert response.status_code == 200
        assert len(response.data) == 0  # student B has no attempts of their own


@pytest.mark.django_db
class TestCoursePermissions:
    def test_student_can_create_own_course(self, authenticated_client, student_user):
        response = authenticated_client.post(
            reverse("course-list"),
            {"name": "Data Structures", "code": "CSC 301"},
        )
        assert response.status_code == 201
        assert response.data["owner"] == student_user.id
        assert response.data["is_mine"] is True

    def test_admin_can_create_curated_course(self, admin_client):
        response = admin_client.post(
            reverse("course-list"),
            {"name": "Data Structures", "code": "CSC 301"},
        )
        assert response.status_code == 201
        assert response.data["owner"] is None

    def test_course_detail_includes_its_topics(self, admin_client, topic):
        # topic fixture creates a standalone topic — attach it to a
        # newly created course and confirm the detail view nests it.
        course_response = admin_client.post(
            reverse("course-list"), {"name": "Data Structures", "code": "CSC 301"}
        )
        course_id = course_response.data["id"]

        topic.course_id = course_id
        topic.save()

        detail_response = admin_client.get(reverse("course-detail", args=[course_id]))
        assert detail_response.status_code == 200
        assert detail_response.data["topic_count"] == 1
        assert len(detail_response.data["topics"]) == 1
        assert detail_response.data["topics"][0]["id"] == topic.id

    def test_student_does_not_see_others_private_courses(self, api_client, django_user_model):
        owner = django_user_model.objects.create_user(
            email="courseowner@example.com", username="courseowner", full_name="Owner",
            password="pass1234", role="student",
        )
        other = django_user_model.objects.create_user(
            email="courseother@example.com", username="courseother", full_name="Other",
            password="pass1234", role="student",
        )

        api_client.force_authenticate(user=owner)
        api_client.post(reverse("course-list"), {"name": "Private Course"})

        api_client.force_authenticate(user=other)
        response = api_client.get(reverse("course-list"))
        names = [c["name"] for c in response.data]
        assert "Private Course" not in names


@pytest.mark.django_db
class TestCourseProgress:
    # Rolls the existing per-topic mastery up to the course level. The
    # data is produced by the mastery signal, which fires whenever an
    # Attempt is saved — so these tests create Attempts (exactly as the
    # mastery app's own tests do) and assert the aggregated shape.

    # --- helpers -------------------------------------------------------
    def _add_topic(self, course, name, order=0):
        return Topic.objects.create(name=name, course=course, order=order)

    def _study(self, student, topic, score):
        # Creating an Attempt fires the mastery post_save signal, which
        # is what builds the StudentProfile this endpoint reads back.
        quiz = Quiz.objects.create(topic=topic, title=f"{topic.name} Quiz")
        Attempt.objects.create(
            student=student, quiz=quiz, score=score, time_spent_seconds=10
        )

    # --- tests ---------------------------------------------------------
    def test_progress_requires_auth(self, api_client):
        course = Course.objects.create(name="Data Structures")
        response = api_client.get(reverse("course-progress", args=[course.id]))
        assert response.status_code == 401

    def test_empty_course_returns_zeroed_progress(self, authenticated_client):
        # No topics at all — must not divide by zero, and must report a
        # clean "nothing here yet" rather than erroring.
        course = Course.objects.create(name="Empty Course")
        response = authenticated_client.get(reverse("course-progress", args=[course.id]))
        assert response.status_code == 200
        assert response.data["topics_total"] == 0
        assert response.data["topics_studied"] == 0
        assert response.data["completion_percent"] == 0.0
        assert response.data["average_score"] is None
        assert response.data["mastery_level"] is None
        assert response.data["strongest_topic"] is None
        assert response.data["weakest_topic"] is None
        assert response.data["topics"] == []

    def test_topics_present_but_none_studied(self, authenticated_client):
        course = Course.objects.create(name="Data Structures")
        self._add_topic(course, "Arrays")
        self._add_topic(course, "Trees")
        response = authenticated_client.get(reverse("course-progress", args=[course.id]))
        assert response.status_code == 200
        assert response.data["topics_total"] == 2
        assert response.data["topics_studied"] == 0
        # A brand-new student is "not started" (null), NOT mislabeled weak.
        assert response.data["mastery_level"] is None
        assert response.data["average_score"] is None
        assert all(t["studied"] is False for t in response.data["topics"])
        assert all(t["mastery_level"] is None for t in response.data["topics"])

    def test_rollup_computes_average_and_extremes(self, authenticated_client, student_user):
        course = Course.objects.create(name="Data Structures")
        arrays = self._add_topic(course, "Arrays", order=0)
        trees = self._add_topic(course, "Trees", order=1)
        self._add_topic(course, "Graphs", order=2)  # left unstudied

        self._study(student_user, arrays, score=90)  # strong
        self._study(student_user, trees, score=40)   # weak

        response = authenticated_client.get(reverse("course-progress", args=[course.id]))
        assert response.status_code == 200
        assert response.data["topics_total"] == 3
        assert response.data["topics_studied"] == 2
        assert response.data["completion_percent"] == 66.67
        # Average over STUDIED topics only: (90 + 40) / 2 = 65 -> average.
        # The unstudied "Graphs" topic must NOT drag this down.
        assert response.data["average_score"] == 65.0
        assert response.data["mastery_level"] == "average"
        assert response.data["strongest_topic"]["name"] == "Arrays"
        assert response.data["strongest_topic"]["mastery_level"] == "strong"
        assert response.data["weakest_topic"]["name"] == "Trees"
        assert response.data["weakest_topic"]["mastery_level"] == "weak"

    def test_only_this_courses_topics_are_counted(self, authenticated_client, student_user):
        course = Course.objects.create(name="Data Structures")
        other_course = Course.objects.create(name="Algorithms")
        arrays = self._add_topic(course, "Arrays")
        other_topic = self._add_topic(other_course, "Dynamic Programming")

        self._study(student_user, arrays, score=80)
        self._study(student_user, other_topic, score=100)  # different course

        response = authenticated_client.get(reverse("course-progress", args=[course.id]))
        assert response.status_code == 200
        # Only the one topic in THIS course counts, never the other's.
        assert response.data["topics_total"] == 1
        assert response.data["topics_studied"] == 1
        assert response.data["average_score"] == 80.0
        names = [t["name"] for t in response.data["topics"]]
        assert "Dynamic Programming" not in names

    def test_cannot_see_another_users_private_course(self, api_client, django_user_model):
        owner = django_user_model.objects.create_user(
            email="owner-prog@example.com", username="ownerprog", full_name="Owner",
            password="pass1234", role="student",
        )
        other = django_user_model.objects.create_user(
            email="other-prog@example.com", username="otherprog", full_name="Other",
            password="pass1234", role="student",
        )
        private_course = Course.objects.create(name="Private Study", owner=owner)

        api_client.force_authenticate(user=other)
        response = api_client.get(reverse("course-progress", args=[private_course.id]))
        # Not in the requester's visible queryset -> 404 (not 403), same
        # privacy reasoning as the rest of the app.
        assert response.status_code == 404

    def test_recommendations_are_scoped_to_this_course(self, authenticated_client, student_user):
        course = Course.objects.create(name="Data Structures")
        other_course = Course.objects.create(name="Algorithms")
        weak_here = self._add_topic(course, "Trees")
        weak_elsewhere = self._add_topic(other_course, "Greedy")

        self._study(student_user, weak_here, score=30)       # weak -> recommendation
        self._study(student_user, weak_elsewhere, score=20)  # weak -> recommendation (other course)

        # The student has two recommendations in total, one per course...
        assert Recommendation.objects.filter(student=student_user).count() == 2

        response = authenticated_client.get(reverse("course-progress", args=[course.id]))
        assert response.status_code == 200
        # ...but this course's progress only surfaces its own.
        assert len(response.data["recommendations"]) == 1
        assert response.data["recommendations"][0]["topic_name"] == "Trees"
