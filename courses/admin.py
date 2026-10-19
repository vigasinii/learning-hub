from django import forms
from django.contrib import admin

from .models import Choice, Course, Enrollment, Lesson, LessonProgress, Question, Quiz, QuizAttempt


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "instructor", "status", "created_at")
    list_filter = ("status", "instructor")
    list_select_related = ("instructor",)
    search_fields = ("title", "description")
    inlines = [LessonInline]


class ChoiceFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        kept = [
            f.cleaned_data
            for f in self.forms
            if hasattr(f, "cleaned_data") and f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        if len(kept) < 2:
            raise forms.ValidationError("A question needs at least two answer options.")
        if sum(1 for c in kept if c.get("is_correct")) != 1:
            raise forms.ValidationError("Mark exactly one option as correct.")


class ChoiceInline(admin.TabularInline):
    model = Choice
    formset = ChoiceFormSet
    extra = 2


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "quiz", "order")
    list_select_related = ("quiz",)
    list_filter = ("quiz",)
    inlines = [ChoiceInline]


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    show_change_link = True


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "pass_mark")
    inlines = [QuestionInline]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("learner", "course", "enrolled_at")
    list_filter = ("course",)
    list_select_related = ("learner", "course")
    search_fields = ("learner__username",)


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "lesson", "completed_at")
    list_filter = ("lesson__course",)
    list_select_related = ("enrollment__learner", "lesson")


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "quiz", "correct", "total", "percent", "passed", "created_at")
    list_filter = ("passed", "quiz")
    list_select_related = ("enrollment__learner", "quiz")
