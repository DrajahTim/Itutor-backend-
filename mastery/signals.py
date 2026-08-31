from datetime import timedelta

from django.db.models import Avg
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from learning.models import Attempt, AttemptAnswer

from .models import Recommendation, ReviewSchedule, StudentProfile


def calculate_mastery(avg_score):
    if avg_score < 50:
        return "weak"
    elif avg_score < 75:
        return "average"
    return "strong"


# --- Spaced repetition (SM-2) ---------------------------------------------
# Tuning constants, named rather than inlined so the scheduling rules are
# readable and adjustable in one place.
EASE_START = 2.5      # SM-2's standard starting ease
EASE_BONUS = 0.1      # added on a correct answer
EASE_PENALTY = 0.2    # subtracted on a wrong answer
EASE_MAX = 2.8        # cap, so intervals can't balloon without bound
EASE_MIN = 1.3        # standard SM-2 floor — never goes below this
FIRST_INTERVAL_DAYS = 1   # after the 1st consecutive correct answer
SECOND_INTERVAL_DAYS = 6  # after the 2nd — the classic SM-2 jump


def schedule_review(ease_factor, interval_days, repetitions, is_correct, now=None):
    """
    Simplified SM-2: given the current schedule state and whether the
    student just answered correctly, return the next state.

    Deliberately pure — no DB access, no model instances, no side effects.
    All the scheduling logic is therefore unit-testable without touching
    the database, the same way calculate_mastery is.

    Returns a dict of ease_factor / interval_days / repetitions /
    next_review_at, ready to splat into update_or_create's defaults.
    """
    now = now or timezone.now()

    if is_correct:
        repetitions += 1
        if repetitions == 1:
            interval_days = FIRST_INTERVAL_DAYS
        elif repetitions == 2:
            interval_days = SECOND_INTERVAL_DAYS
        else:
            # From the 3rd correct answer on, the interval compounds by
            # the ease factor. Uses the ease as it was BEFORE this
            # answer's bonus, so the bonus only affects future intervals
            # — this keeps one answer from both lengthening the interval
            # and raising the multiplier that produced it.
            interval_days = round(interval_days * ease_factor)
        ease_factor = min(ease_factor + EASE_BONUS, EASE_MAX)
    else:
        # A miss sends the question back to the start: seen again
        # tomorrow, and slightly harder from now on. repetitions is what
        # makes this a genuine reset rather than just a short interval.
        repetitions = 0
        interval_days = FIRST_INTERVAL_DAYS
        ease_factor = max(ease_factor - EASE_PENALTY, EASE_MIN)

    return {
        "ease_factor": round(ease_factor, 2),
        "interval_days": interval_days,
        "repetitions": repetitions,
        "next_review_at": now + timedelta(days=interval_days),
    }


def record_review(student, question, is_correct, now=None):
    """
    Advance (or create) this student's ReviewSchedule row for a question.

    The single entry point for scheduling, called from two places: the
    post_save signal below (normal quiz submissions) and the review
    submit endpoint (dedicated review sessions). Both paths therefore
    produce identical scheduling behaviour by construction, rather than
    by two implementations agreeing.
    """
    now = now or timezone.now()

    # Read current state, defaulting to a fresh card when this is the
    # first time the student has seen the question.
    schedule = ReviewSchedule.objects.filter(student=student, question=question).first()
    if schedule is None:
        ease_factor, interval_days, repetitions = EASE_START, 1, 0
    else:
        ease_factor = schedule.ease_factor
        interval_days = schedule.interval_days
        repetitions = schedule.repetitions

    state = schedule_review(ease_factor, interval_days, repetitions, is_correct, now=now)

    # update_or_create keyed on the unique_together pair — one row per
    # (student, question), updated in place, same as StudentProfile.
    schedule, _ = ReviewSchedule.objects.update_or_create(
        student=student,
        question=question,
        defaults={**state, "last_reviewed_at": now},
    )
    return schedule


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


@receiver(post_save, sender=AttemptAnswer)
def update_review_schedule_on_answer(sender, instance, created, **kwargs):
    # Fires every time a question is answered, from anywhere — a normal
    # quiz submission via SubmitAttemptView or a dedicated review
    # submission. Hooking the signal to AttemptAnswer rather than calling
    # record_review from SubmitAttemptView keeps the learning app free of
    # any knowledge of spaced repetition, exactly like the Attempt signal
    # above keeps it free of mastery logic.
    if not created:
        return

    record_review(
        student=instance.attempt.student,
        question=instance.question,
        is_correct=instance.is_correct,
    )