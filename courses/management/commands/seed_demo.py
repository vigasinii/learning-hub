from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from courses.models import Choice, Course, Enrollment, Lesson, LessonProgress, Question, Quiz

PASSWORD = "demo-pass-123"
COURSE_TITLE = "E-filing for Court Clerks"
DRAFT_TITLE = "Draft: Advanced Case Management"

LESSONS = [
    ("Why e-filing?", "Courts are moving from paper to electronic filing. This lesson explains the benefits and the timeline."),
    ("Creating your account", "Register on the e-filing portal using your official email address and verify it."),
    ("Submitting a document", "Choose the case, upload the PDF, select the document type and pay any fee."),
    ("Tracking and corrections", "Use the dashboard to track the status and respond to clerk rejections quickly."),
]

QUESTIONS = [
    ("Which file format should filings be uploaded in?", ["Word", "PDF", "JPEG", "Plain text"], 1),
    ("What do you use to register on the portal?", ["A personal email", "Your official email", "A phone number only"], 1),
    ("Where can you track a filing's status?", ["The dashboard", "A paper register", "Nowhere"], 0),
]


class Command(BaseCommand):
    help = "Create demo instructor, learners, a published course (lessons + quiz) and a draft course."

    @transaction.atomic
    def handle(self, *args, **options):
        instructor = self._user("instructor1", User.Role.INSTRUCTOR)
        learner1 = self._user("learner1", User.Role.LEARNER)
        learner2 = self._user("learner2", User.Role.LEARNER)

        course, _ = Course.objects.get_or_create(
            instructor=instructor,
            title=COURSE_TITLE,
            defaults={
                "description": "A short course on submitting and tracking documents with the new e-filing process.",
                "status": Course.Status.PUBLISHED,
            },
        )
        for order, (title, content) in enumerate(LESSONS, start=1):
            Lesson.objects.get_or_create(course=course, order=order, defaults={"title": title, "content": content})

        quiz, _ = Quiz.objects.get_or_create(course=course, defaults={"title": "E-filing quiz", "pass_mark": 70})
        for order, (text, options, right) in enumerate(QUESTIONS, start=1):
            question, created = Question.objects.get_or_create(quiz=quiz, text=text, defaults={"order": order})
            if created or not question.choices.exists():
                for i, option in enumerate(options):
                    Choice.objects.create(question=question, text=option, is_correct=(i == right))

        Course.objects.get_or_create(
            instructor=instructor,
            title=DRAFT_TITLE,
            defaults={"description": "Work in progress, not visible to learners.", "status": Course.Status.DRAFT},
        )

        enrollment1, _ = Enrollment.objects.get_or_create(learner=learner1, course=course)
        Enrollment.objects.get_or_create(learner=learner2, course=course)
        for lesson in course.lessons.all()[:2]:
            LessonProgress.objects.get_or_create(enrollment=enrollment1, lesson=lesson)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  instructor1 / {PASSWORD}  (instructor)")
        self.stdout.write(f"  learner1    / {PASSWORD}  (learner, 2 of 4 lessons done)")
        self.stdout.write(f"  learner2    / {PASSWORD}  (learner, just enrolled)")
        self.stdout.write("Passwords are only set when an account is first created.")

    def _user(self, username, role):
        user, created = User.objects.get_or_create(username=username, defaults={"role": role})
        if created:
            user.set_password(PASSWORD)
            user.save()
        elif user.role != role:
            raise CommandError(
                f"User '{username}' already exists with role '{user.role}', expected '{role}'. "
                "Rename or remove that account, then run seed_demo again."
            )
        return user
