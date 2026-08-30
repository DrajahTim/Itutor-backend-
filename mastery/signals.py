from django.db.models import Avg
from django.db.models.signals import post_save
from django.dispatch import receiver

from learning.models import Attempt

from .models import Recommendation, StudentProfile


def calculate_mastery(avg_score):
    if avg_score < 50:
        return "weak"
    elif avg_score < 75:
        return "average"
    return "strong"


@receiver(post_save, sender=Attempt)
def update_profile_on_attempt(sender, instance, created, **kwargs):
    # Fires automatically every time an Attempt is saved (i.e. right
    # after SubmitAttemptView finishes grading a quiz). This is what
    # makes the system "adaptive" without the learning app needing to
    # know anything about mastery/recommendation logic — it just saves
    # an Attempt, and this app reacts to that.
    if not created:
        return

    student = instance.student
    topic = instance.quiz.topic

    # Recalculate the average across ALL of this student's attempts on
    # quizzes belonging to this topic (not just this one attempt).
    topic_attempts = Attempt.objects.filter(student=student, quiz__topic=topic)
    avg_score = topic_attempts.aggregate(avg=Avg("score"))["avg"] or 0
    attempts_count = topic_attempts.count()
    mastery_level = calculate_mastery(avg_score)

    profile, _ = StudentProfile.objects.update_or_create(
        student=student,
        topic=topic,
        defaults={
            "avg_score": round(avg_score, 2),
            "attempts_count": attempts_count,
            "mastery_level": mastery_level,
        },
    )

    # Only generate a recommendation when the student is weak — no need
    # to spam recommendations for students already doing fine.
    if mastery_level == "weak":
        Recommendation.objects.create(
            student=student,
            topic=topic,
            reason=f"Average score in {topic.name} is {round(avg_score, 1)}%, below the 50% mastery threshold.",
        )