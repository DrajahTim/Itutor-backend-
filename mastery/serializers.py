from rest_framework import serializers

from .models import Recommendation, StudentProfile


class StudentProfileSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            "id", "topic", "topic_name", "mastery_level",
            "avg_score", "attempts_count", "last_activity_at",
        ]


class RecommendationSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = Recommendation
        fields = ["id", "topic", "topic_name", "reason", "created_at"]