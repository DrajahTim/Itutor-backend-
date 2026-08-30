from django.contrib import admin

from .models import Attempt, AttemptAnswer, Lesson, Question, Quiz, Topic


class LessonInline(admin.TabularInline):
    # Lets you add/edit lessons directly from a Topic's admin page,
    # instead of navigating to a separate Lesson list.
    model = Lesson
    extra = 1


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [LessonInline]


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "topic", "passing_score")
    inlines = [QuestionInline]


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "quiz", "score", "submitted_at")
    readonly_fields = ("student", "quiz", "score", "time_spent_seconds", "submitted_at")


admin.site.register(Lesson)
admin.site.register(Question)
admin.site.register(AttemptAnswer)

