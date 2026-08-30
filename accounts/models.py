from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # A user is either a student (default) or an admin.
    # Admins will later be allowed to create/edit lessons and quizzes.
    ROLE_CHOICES = (
        ("student", "Student"),
        ("admin", "Admin"),
    )

    # Django's AbstractUser already has a `username` field, but we're
    # switching the login identifier to email instead (see USERNAME_FIELD
    # below). We still keep `unique=True` here so no two accounts can
    # share an email.
    email = models.EmailField(unique=True)

    # Display name shown in the UI (separate from username/email).
    full_name = models.CharField(max_length=255)

    # Controls access level. Defaults to "student" so normal signups
    # don't accidentally get admin rights.
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="student")

    # Timestamp set automatically the first time the row is created.
    created_at = models.DateTimeField(auto_now_add=True)

    # Tell Django to use email (not username) when logging in.
    USERNAME_FIELD = "email"

    # Fields Django will still prompt for when creating a user via
    # `createsuperuser` in the terminal, besides USERNAME_FIELD + password.
    REQUIRED_FIELDS = ["username", "full_name"]

    def __str__(self):
        # This is what shows up in the Django admin panel and shell,
        # e.g. when you print a User object or see it listed.
        return self.email
