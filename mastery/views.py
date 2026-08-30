from django.db.models import Count, Max, Q, Sum
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from learning.models import Attempt, AttemptAnswer, Question
from .models import Recommendation, StudentProfile
from .serializers import RecommendationSerializer, StudentProfileSerializer


class MyProfilesView(generics.ListAPIView):
    # GET /api/mastery/profiles/mine/ — a student's mastery level
    # across every topic they've attempted.
    serializer_class = StudentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return StudentProfile.objects.filter(student=self.request.user)


class MyRecommendationsView(generics.ListAPIView):
    # GET /api/mastery/recommendations/mine/ — every recommendation
    # ever generated for this student, most recent first.
    serializer_class = RecommendationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Recommendation.objects.filter(student=self.request.user)


# How many "most missed" questions to surface. Enough to be useful as a
# study list without turning the analytics page into a wall of text.
MOST_MISSED_LIMIT = 10


class AnalyticsOverviewView(APIView):
    # GET /api/mastery/analytics/overview/
    #
    # The data-analyst view of a single student's own performance, in one
    # round trip: a headline summary, a per-topic table, a chronological
    # score trend, and the questions they miss most. It reads the same
    # StudentProfile rows the dashboard uses (so numbers never diverge)
    # and layers the raw Attempt / AttemptAnswer history on top for the
    # things a profile alone can't answer — "how am I trending?" and
    # "which exact questions keep tripping me up?".
    #
    # Honesty-first, same as the rest of the app: mastery_level always
    # comes from the stored band (never re-derived from a raw score), and
    # averages are studied-only so untouched topics can't distort them.
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Same-app import, kept local to mirror the lazy cross-app style
        # used elsewhere and avoid any import-time coupling to signals.
        from .signals import calculate_mastery

        student = request.user

        # --- Per-topic table ------------------------------------------
        # StudentProfile is the source of truth for mastery/avg/attempts
        # (one row per studied topic). We enrich each row with best score
        # and total time, which live only on the raw attempts.
        profiles = list(
            StudentProfile.objects.filter(student=student).select_related("topic")
        )

        # Aggregate this student's attempts up to the topic level in a
        # single query (best score + total time + count per topic),
        # keyed by topic id for an O(1) merge with the profile rows.
        attempt_agg = {
            row["quiz__topic"]: row
            for row in (
                Attempt.objects.filter(student=student)
                .values("quiz__topic")
                .annotate(
                    best_score=Max("score"),
                    total_time=Sum("time_spent_seconds"),
                    n=Count("id"),
                )
            )
        }

        topic_rows = []
        for profile in profiles:
            agg = attempt_agg.get(profile.topic_id, {})
            topic_rows.append({
                "topic": profile.topic_id,
                "topic_name": profile.topic.name,
                "mastery_level": profile.mastery_level,
                "avg_score": round(profile.avg_score, 2),
                "best_score": round(agg.get("best_score") or 0.0, 2),
                "attempts_count": profile.attempts_count,
                "total_time_seconds": agg.get("total_time") or 0,
                "last_activity_at": profile.last_activity_at,
            })
        # Deterministic default order: weakest first, so the table opens
        # on what needs attention. Ties break on name for stability.
        topic_rows.sort(key=lambda r: (r["avg_score"], r["topic_name"]))

        # --- Headline summary -----------------------------------------
        studied_scores = [p.avg_score for p in profiles]
        topics_studied = len(studied_scores)
        # Studied-only mean of per-topic averages — identical definition
        # to the dashboard's "Avg. score" tile and the course rollup.
        if topics_studied:
            average_score = round(sum(studied_scores) / topics_studied, 2)
            mastery_level = calculate_mastery(average_score)
        else:
            average_score = None
            mastery_level = None

        distribution = {
            "weak": sum(1 for p in profiles if p.mastery_level == "weak"),
            "average": sum(1 for p in profiles if p.mastery_level == "average"),
            "strong": sum(1 for p in profiles if p.mastery_level == "strong"),
        }

        total_attempts = sum(p.attempts_count for p in profiles)
        total_time_seconds = (
            Attempt.objects.filter(student=student).aggregate(t=Sum("time_spent_seconds"))["t"]
            or 0
        )

        summary = {
            "total_attempts": total_attempts,
            "topics_studied": topics_studied,
            "average_score": average_score,
            "mastery_level": mastery_level,
            "total_time_seconds": total_time_seconds,
            "distribution": distribution,
        }

        # --- Score trend ----------------------------------------------
        # Every attempt in chronological order — one point per quiz
        # submission — so the client can draw a "score over time" line
        # and the student can literally see themselves improving.
        trend = [
            {
                "attempt_id": attempt.id,
                "topic": attempt.quiz.topic_id,
                "topic_name": attempt.quiz.topic.name,
                "score": round(attempt.score, 2),
                "submitted_at": attempt.submitted_at,
            }
            for attempt in (
                Attempt.objects.filter(student=student)
                .select_related("quiz__topic")
                .order_by("submitted_at")
            )
        ]

        # --- Most-missed questions ------------------------------------
        # Group this student's answers by question, counting how often
        # each was answered and how often it was wrong. Only questions
        # missed at least once qualify; worst offenders first.
        missed_agg = (
            AttemptAnswer.objects.filter(attempt__student=student)
            .values("question")
            .annotate(
                answered=Count("id"),
                misses=Count("id", filter=Q(is_correct=False)),
            )
            .filter(misses__gt=0)
            .order_by("-misses", "question")[:MOST_MISSED_LIMIT]
        )

        # Fetch the referenced questions in one query for text + topic,
        # then stitch them onto the aggregates in ranked order.
        question_map = {
            q.id: q
            for q in Question.objects.filter(
                id__in=[row["question"] for row in missed_agg]
            ).select_related("quiz__topic")
        }
        most_missed = []
        for row in missed_agg:
            question = question_map.get(row["question"])
            if question is None:
                continue
            answered = row["answered"]
            misses = row["misses"]
            most_missed.append({
                "question_id": question.id,
                "text": question.text,
                "topic": question.quiz.topic_id,
                "topic_name": question.quiz.topic.name,
                "answered": answered,
                "misses": misses,
                "miss_rate": round(misses / answered * 100, 1) if answered else 0.0,
            })

        return Response({
            "summary": summary,
            "topics": topic_rows,
            "score_trend": trend,
            "most_missed": most_missed,
        })
