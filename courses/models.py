from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from django.db.models import Q
from django.urls import reverse

User = settings.AUTH_USER_MODEL


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    instructor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="courses_taught",
        limit_choices_to={"role": "instructor"},
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    def get_absolute_url(self):
        return reverse("course_detail", args=[self.pk])


class Lesson(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    content = models.TextField()
    video_url = models.URLField(blank=True)
    attachment = models.FileField(
        upload_to="lesson_attachments/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "png", "jpg", "jpeg"]
            )
        ],
    )
    order = models.PositiveIntegerField(help_text="Position within the course (1 = first).")

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["course", "order"], name="unique_lesson_order_per_course")
        ]

    def __str__(self):
        return f"{self.order}. {self.title}"


class Enrollment(models.Model):
    learner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="enrollments",
        limit_choices_to={"role": "learner"},
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enrolled_at"]
        constraints = [
            models.UniqueConstraint(fields=["learner", "course"], name="unique_enrollment")
        ]

    def __str__(self):
        return f"{self.learner} in {self.course}"


class LessonProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "lesson progress"
        constraints = [
            models.UniqueConstraint(fields=["enrollment", "lesson"], name="unique_lesson_progress")
        ]

    def clean(self):
        if self.enrollment_id and self.lesson_id and self.lesson.course_id != self.enrollment.course_id:
            raise ValidationError("The lesson does not belong to the enrolled course.")

    def __str__(self):
        return f"{self.enrollment.learner} completed {self.lesson}"


class Quiz(models.Model):
    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name="quiz")
    title = models.CharField(max_length=200)
    pass_mark = models.PositiveSmallIntegerField(
        default=70,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Percentage needed to pass (1-100).",
    )

    class Meta:
        verbose_name_plural = "quizzes"

    def __str__(self):
        return self.title


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.CharField(max_length=500)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["question"],
                condition=Q(is_correct=True),
                name="one_correct_choice_per_question",
            )
        ]

    def __str__(self):
        return self.text


class QuizAttempt(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="attempts")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    correct = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    percent = models.PositiveSmallIntegerField()
    passed = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.enrollment_id and self.quiz_id and self.quiz.course_id != self.enrollment.course_id:
            raise ValidationError("The quiz does not belong to the enrolled course.")
        if self.total is not None and self.correct is not None and self.correct > self.total:
            raise ValidationError("Correct answers cannot exceed the number of questions.")

    def __str__(self):
        return f"{self.enrollment.learner}: {self.correct}/{self.total}"


def _delete_file_on_commit(storage, name):
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(post_delete, sender=Lesson)
def delete_attachment_with_lesson(sender, instance, **kwargs):
    _delete_file_on_commit(instance.attachment.storage, instance.attachment.name)


@receiver(pre_save, sender=Lesson)
def delete_replaced_attachment(sender, instance, **kwargs):
    if not instance.pk:
        return
    old_name = sender.objects.filter(pk=instance.pk).values_list("attachment", flat=True).first()
    if old_name and old_name != instance.attachment.name:
        _delete_file_on_commit(instance.attachment.storage, old_name)
