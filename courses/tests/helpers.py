import shutil
import tempfile

from django.test import override_settings

from accounts.models import User
from courses.models import Choice, Course, Enrollment, Lesson, Question, Quiz


def make_user(username, role):
    return User.objects.create_user(username=username, password="pw-12345-x", role=role)


def make_course(instructor, title="Course", status=Course.Status.PUBLISHED, lessons=3):
    course = Course.objects.create(instructor=instructor, title=title, description="d", status=status)
    for i in range(1, lessons + 1):
        Lesson.objects.create(course=course, title=f"Lesson {i}", content="c", order=i)
    return course


def make_quiz(course, pass_mark=70, n_questions=3):
    quiz = Quiz.objects.create(course=course, title="Quiz", pass_mark=pass_mark)
    for i in range(1, n_questions + 1):
        q = Question.objects.create(quiz=quiz, text=f"Q{i}", order=i)
        Choice.objects.create(question=q, text="right", is_correct=True)
        Choice.objects.create(question=q, text="wrong", is_correct=False)
    return quiz


def answers(quiz, right_count):
    data = {}
    for i, q in enumerate(quiz.questions.prefetch_related("choices")):
        choices = list(q.choices.all())
        pick = next(c for c in choices if c.is_correct == (i < right_count))
        data[f"question_{q.id}"] = pick.id
    return data


def enroll(learner, course):
    return Enrollment.objects.create(learner=learner, course=course)


class TempMediaMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.mkdtemp(prefix="lms-test-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)
        super().tearDownClass()
