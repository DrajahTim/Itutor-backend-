from django.conf import settings
from django.db import models

from learning.models import Question, Topic


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


class ReviewSchedule(models.Model):
    # Spaced repetition state for one question, for one student.
    #
    # Where StudentProfile tracks mastery at the topic level, this tracks
    # it at the individual question level: how well the student knows
    # THIS fact, and when they should next be shown it. The SM-2 numbers
    # (ease_factor / interval_days / repetitions) live here rather than
    # being recomputed, because SM-2 is inherently stateful — each
    # review's interval depends on the one before it.
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_schedules"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="review_schedules"
    )
    # How "easy" this question is for this student. Higher = intervals
    # grow faster. 2.5 is the standard SM-2 starting value.
    ease_factor = models.FloatField(default=2.5)
    # Days until the next review. Grows on success, resets to 1 on a miss.
    interval_days = models.PositiveIntegerField(default=1)
    # Consecutive correct answers. Reset to 0 by any wrong answer, which
    # is what sends the question back to the start of the schedule.
    repetitions = models.PositiveIntegerField(default=0)
    # When this question becomes due again. The "due" endpoint is just
    # a filter on this field, so it's the one field worth indexing.
    next_review_at = models.DateTimeField(db_index=True)
    # Null until the first review — distinguishes "scheduled but never
    # seen" from "reviewed at least once".
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # One schedule row per (student, question), updated in place and
        # never duplicated — same reasoning as StudentProfile's
        # unique_together on (student, topic).
        unique_together = ("student", "question")
        # Soonest-due first: the natural order for "what should I study
        # now?", so views don't need to re-specify it.
        ordering = ["next_review_at"]

    def __str__(self):
        return f"{self.student.email} - Q{self.question_id} (due {self.next_review_at:%Y-%m-%d})"
