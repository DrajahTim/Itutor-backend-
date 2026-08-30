from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


class UserAdmin(BaseUserAdmin):
    # Customize which fields show up in the admin list view and edit form,
    # since our User model has different fields than Django's default one.
    list_display = ("email", "username", "full_name", "role", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Additional Info", {"fields": ("full_name", "role")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Additional Info", {"fields": ("email", "full_name", "role")}),
    )


admin.site.register(User, UserAdmin)