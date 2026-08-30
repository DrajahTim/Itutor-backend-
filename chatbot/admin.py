from django.contrib import admin

from .models import ChatMessage, CourseDocument, DocumentChunk


class DocumentChunkInline(admin.TabularInline):
    model = DocumentChunk
    extra = 0
    readonly_fields = ("chunk_index", "content")
    # Never show the raw embedding vector in the admin — it's a 384-number
    # list, completely unreadable and useless to look at manually.
    exclude = ("embedding",)


@admin.register(CourseDocument)
class CourseDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "topic", "source_type", "created_at")
    inlines = [DocumentChunkInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("student", "topic", "role", "created_at")
    list_filter = ("role", "topic")
    readonly_fields = ("student", "topic", "role", "content", "created_at")