"""
Shared pytest fixtures available to every test file automatically —
no imports needed in the test files themselves.
"""
import pytest
from rest_framework.test import APIClient

from learning.models import Question, Quiz, Topic


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def student_user(django_user_model):
    return django_user_model.objects.create_user(
        email="student@example.com",
        username="student1",
        full_name="Student One",
        password="TestPass123!",
        role="student",
    )


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_user(
        email="admin@example.com",
        username="admin1",
        full_name="Admin One",
        password="TestPass123!",
        role="admin",
    )


@pytest.fixture
def authenticated_client(api_client, student_user):
    api_client.force_authenticate(user=student_user)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def topic():
    return Topic.objects.create(name="Sorting Algorithms", slug="sorting", order=1)


@pytest.fixture
def quiz_with_questions(topic):
    quiz = Quiz.objects.create(topic=topic, title="Sorting Quiz", passing_score=60)
    q1 = Question.objects.create(
        quiz=quiz,
        text="What is the worst-case time complexity of Bubble Sort?",
        option_a="O(n)", option_b="O(n log n)", option_c="O(n^2)", option_d="O(1)",
        correct_option="C",
    )
    q2 = Question.objects.create(
        quiz=quiz,
        text="Which algorithm repeatedly swaps adjacent elements?",
        option_a="Bubble Sort", option_b="Binary Search", option_c="Merge Sort", option_d="Hashing",
        correct_option="A",
    )
    return quiz, [q1, q2]