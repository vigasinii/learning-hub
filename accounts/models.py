from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        LEARNER = "learner", "Learner"
        INSTRUCTOR = "instructor", "Instructor"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.LEARNER)

    @property
    def is_instructor(self):
        return self.role == self.Role.INSTRUCTOR

    @property
    def is_learner(self):
        return self.role == self.Role.LEARNER

    def clean(self):
        super().clean()
        if self.pk and self.role == self.Role.LEARNER and self.owns_courses():
            raise ValidationError(
                {"role": "This user still owns courses. Reassign or delete them before making the user a learner."}
            )

    def owns_courses(self):
        return self.courses_taught.exists()
