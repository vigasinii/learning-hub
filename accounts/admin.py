from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LMSUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (("LMS", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("LMS", {"fields": ("role",)}),)
    actions = ["make_instructor", "make_learner"]

    @admin.action(description="Promote selected users to instructor")
    def make_instructor(self, request, queryset):
        count = queryset.update(role=User.Role.INSTRUCTOR)
        self.message_user(request, f"{count} user(s) are now instructors.", messages.SUCCESS)

    @admin.action(description="Set selected users to learner")
    def make_learner(self, request, queryset):
        blocked = list(queryset.filter(courses_taught__isnull=False).distinct().order_by("username"))
        eligible = queryset.exclude(pk__in=[u.pk for u in blocked])
        count = eligible.update(role=User.Role.LEARNER)
        if count:
            self.message_user(request, f"{count} user(s) are now learners.", messages.SUCCESS)
        if blocked:
            names = ", ".join(u.username for u in blocked)
            self.message_user(
                request,
                f"Not changed (they still own courses; reassign or delete the courses first): {names}.",
                messages.WARNING,
            )
