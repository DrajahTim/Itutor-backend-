from django.conf import settings
from django.db import models

from learning.models import Topic


class StudentProfile(models.Model):
    # One row per (student, topic) pair — tracks how a student is doing
    # in a specific topic, not the system as a whole.
    MASTERY_CHOICES = (
        ("weak", "Weak"),
        ("average", "Average"),
        ("strong", "Strong"),
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profiles"
    )
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="student_profiles")
    mastery_level = models.CharField(max_length=10, choices=MASTERY_CHOICES, default="weak")
    avg_score = models.FloatField(default=0)
    attempts_count = models.PositiveIntegerField(default=0)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        # A student can only have ONE profile per topic — prevents
        # duplicate rows when recalculating after each attempt.
        unique_together = ("student", "topic")

    def __str__(self):
        return f"{self.student.email} - {self.topic.name} ({self.mastery_level})"


class Recommendation(models.Model):
    # A logged suggestion: "review Topic X because Y". Kept even after
    # the student acts on it, so you can show a history in your defense
    # ("here's why the system recommended this").
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations"
    )
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="recommendations")
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student.email} - {self.topic.name}"
# Create your models here.
