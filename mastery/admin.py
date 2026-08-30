from django.contrib import admin

from .models import Recommendation, StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("student", "topic", "mastery_level", "avg_score", "attempts_count")
    list_filter = ("mastery_level", "topic")


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("student", "topic", "reason", "created_at")
    list_filter = ("topic",)
# Register your models here.
