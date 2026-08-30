import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify

class Course(models.Model):
    # Sits above Topic — represents a full syllabus course (e.g. "CSC 301
    # - Data Structures"), following an actual curriculum. Curated
    # courses (owner=None) are visible to everyone; a student can also
    # create their own private course as a personal study grouping,
    # using the exact same hybrid ownership pattern as Topic.
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, blank=True)  # e.g. "CSC 301"
    slug = models.SlugField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_courses",
    )

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        # Same auto-unique-slug pattern as Topic.
        if not self.slug:
            base_slug = slugify(self.name)[:250]
            self.slug = base_slug
            while Course.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}" if self.code else self.name

class Topic(models.Model):
    # The spine of the whole system — everything else (lessons, quizzes,
    # student profiles, recommendations) is organized around a Topic.
    name = models.CharField(max_length=255)
    # No longer globally unique=True: once students can create their own
    # topics, two different students naming a topic "Python Basics"
    # would otherwise collide. Uniqueness is handled in save() instead.
    slug = models.SlugField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    # Controls display/recommended sequence, e.g. "Sorting" before "Graphs".
    order = models.PositiveIntegerField(default=0)
    # None = official, curated topic visible to every student.
    # Set to a User = a private topic only that student can see/use.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_topics",
    )
    # Optional — a topic can belong to a course (following its syllabus
    # structure), or stand alone as a private study topic with no course.
    course = models.ForeignKey(
        "Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topics",
    )

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        # Auto-generate a slug from the name if one wasn't provided, and
        # guarantee it's unique by appending a short random suffix on
        # collision — avoids needing the caller to think about slugs at all.
        if not self.slug:
            base_slug = slugify(self.name)[:250]
            self.slug = base_slug
            while Topic.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Lesson(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=255)
    # Markdown/plain text content — rendering is a frontend concern.
    content = models.TextField()
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.topic.name} - {self.title}"


class Quiz(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="quizzes")
    title = models.CharField(max_length=255)
    # Minimum % score to be considered "passed" — used later by the
    # recommendation engine to decide if a student needs review material.
    passing_score = models.PositiveIntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.topic.name} - {self.title}"


class Question(models.Model):
    OPTION_CHOICES = (
        ("A", "Option A"),
        ("B", "Option B"),
        ("C", "Option C"),
        ("D", "Option D"),
    )
    SOURCE_CHOICES = (
        ("admin", "Admin-authored"),
        ("generated", "LLM-generated"),
    )

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500)
    option_d = models.CharField(max_length=500)
    correct_option = models.CharField(max_length=1, choices=OPTION_CHOICES)
    # A short rationale for why the correct answer is right, shown on the
    # results screen after an attempt so a miss becomes a learning moment.
    # Blank for older/admin questions that predate this field — the UI
    # degrades gracefully when it's empty.
    explanation = models.TextField(blank=True, default="")
    # Distinguishes hand-written questions from ones the LLM generated
    # from a student's uploaded document — useful for debugging quality
    # issues and for a future "flag this question" feature.
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="admin")

    def __str__(self):
        return self.text[:50]


class Attempt(models.Model):
    # One row per student per quiz submission.
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts"
    )
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    # Stored as a percentage (0-100), calculated when the attempt is submitted.
    score = models.FloatField()
    time_spent_seconds = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.email} - {self.quiz.title} ({self.score}%)"


class AttemptAnswer(models.Model):
    # Per-question breakdown of an attempt. Without this table we'd only
    # know the final score, not which specific questions the student
    # struggled with — and that granularity is what the recommendation
    # engine needs later.
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.CharField(max_length=1, choices=Question.OPTION_CHOICES)
    is_correct = models.BooleanField()

    def __str__(self):
        return f"Attempt {self.attempt_id} - Q{self.question_id}"
# Create your models here.
