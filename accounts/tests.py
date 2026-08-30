from django.test import TestCase
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestRegistration:
    def test_register_creates_user_with_student_role(self, api_client):
        response = api_client.post(
            reverse("register"),
            {
                "email": "new@example.com",
                "username": "newuser",
                "full_name": "New User",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 201
        # Even though role isn't sent in the request, it should default
        # to "student" — this is the security guarantee from the
        # serializer's read_only role field + forced "student" in create().
        assert response.data["user"]["role"] == "student"
        assert "access" in response.data
        assert "refresh" in response.data

    def test_register_cannot_set_role_to_admin(self, api_client):
        # Directly tests the security decision made in RegisterSerializer:
        # a crafted request trying to self-assign admin must be ignored.
        response = api_client.post(
            reverse("register"),
            {
                "email": "sneaky@example.com",
                "username": "sneaky",
                "full_name": "Sneaky User",
                "password": "SecurePass123!",
                "role": "admin",
            },
        )
        assert response.status_code == 201
        assert response.data["user"]["role"] == "student"

    def test_register_rejects_duplicate_email(self, api_client, student_user):
        response = api_client.post(
            reverse("register"),
            {
                "email": student_user.email,  # already exists
                "username": "another",
                "full_name": "Another User",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestLogin:
    def test_login_with_correct_credentials(self, api_client, student_user):
        response = api_client.post(
            reverse("login"),
            {"email": student_user.email, "password": "TestPass123!"},
        )
        assert response.status_code == 200
        assert "access" in response.data

    def test_login_with_wrong_password_fails(self, api_client, student_user):
        response = api_client.post(
            reverse("login"),
            {"email": student_user.email, "password": "WrongPassword"},
        )
        assert response.status_code == 401


@pytest.mark.django_db
class TestMeEndpoint:
    def test_me_requires_authentication(self, api_client):
        response = api_client.get(reverse("me"))
        assert response.status_code == 401

    def test_me_returns_own_profile(self, authenticated_client, student_user):
        response = authenticated_client.get(reverse("me"))
        assert response.status_code == 200
        assert response.data["email"] == student_user.email
