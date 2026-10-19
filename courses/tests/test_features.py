import csv
import io

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.forms import QuestionForm
from courses.models import Choice, Course, Enrollment, Lesson, LessonProgress, Question, QuizAttempt

from .helpers import TempMediaMixin, answers, enroll, make_course, make_quiz, make_user


class SignupTests(TestCase):
    PASSWORDS = {"password1": "a-Strong-pass-77", "password2": "a-Strong-pass-77"}

    def test_signup_creates_learner_and_logs_in(self):
        response = self.client.post(reverse("signup"), {"username": "newbie", **self.PASSWORDS})
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(User.objects.get(username="newbie").role, "learner")
        self.assertEqual(self.client.get(reverse("my_courses")).status_code, 200)

    def test_signup_cannot_grant_instructor_role(self):
        for i, value in enumerate(("instructor", "Instructor", "admin")):
            self.client.logout()
            self.client.post(reverse("signup"), {"username": f"sneaky{i}", "role": value, **self.PASSWORDS})
            user = User.objects.get(username=f"sneaky{i}")
            self.assertEqual(user.role, "learner")
            self.assertFalse(user.is_staff or user.is_superuser)
            self.assertEqual(self.client.get(reverse("instructor_courses")).status_code, 403)
            self.assertEqual(self.client.get(reverse("course_create")).status_code, 403)

    def test_signup_page_has_no_role_field(self):
        self.assertNotContains(self.client.get(reverse("signup")), 'name="role"')

    def test_duplicate_username_and_weak_password_rejected(self):
        make_user("taken", "learner")
        self.assertEqual(self.client.post(reverse("signup"), {"username": "taken", **self.PASSWORDS}).status_code, 200)
        weak = {"username": "weak", "password1": "12345678", "password2": "12345678"}
        self.assertEqual(self.client.post(reverse("signup"), weak).status_code, 200)
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_logged_in_user_is_redirected_away_from_signup(self):
        self.client.force_login(make_user("u", "learner"))
        self.assertRedirects(self.client.get(reverse("signup")), reverse("home"))

    def test_login_success_failure_and_next(self):
        make_user("alice", "learner")
        bad = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertEqual(bad.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        good = self.client.post(reverse("login") + "?next=/my-courses/", {"username": "alice", "password": "pw-12345-x"})
        self.assertRedirects(good, "/my-courses/")

    def test_login_does_not_redirect_to_external_next(self):
        make_user("alice", "learner")
        response = self.client.post(
            reverse("login") + "?next=https://evil.example/", {"username": "alice", "password": "pw-12345-x"}
        )
        self.assertRedirects(response, reverse("home"))

    def test_logout_requires_post(self):
        self.client.force_login(make_user("u", "learner"))
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class EnrolmentAndProgressTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.learner = make_user("l", "learner")
        self.course = make_course(self.teacher, lessons=7)
        self.client.force_login(self.learner)

    def test_enrol_is_idempotent_and_listed_in_my_courses(self):
        url = reverse("enroll", args=[self.course.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Enrollment.objects.count(), 1)
        self.assertContains(self.client.get(reverse("my_courses")), self.course.title)

    def test_progress_text_matches_spec_example(self):
        enrollment = enroll(self.learner, self.course)
        for lesson in self.course.lessons.all()[:4]:
            self.client.post(reverse("complete_lesson", args=[lesson.pk]))
        self.assertEqual(enrollment.progress.count(), 4)
        self.assertContains(self.client.get(reverse("my_courses")), "4 of 7 lessons done (57%)")

    def test_completing_twice_does_not_double_count(self):
        enroll(self.learner, self.course)
        lesson = self.course.lessons.first()
        self.client.post(reverse("complete_lesson", args=[lesson.pk]))
        self.client.post(reverse("complete_lesson", args=[lesson.pk]))
        self.assertEqual(LessonProgress.objects.count(), 1)

    def test_my_courses_only_shows_own_enrolments(self):
        other = make_course(self.teacher, "Not mine")
        enroll(make_user("l2", "learner"), other)
        enroll(self.learner, self.course)
        self.assertNotContains(self.client.get(reverse("my_courses")), "Not mine")

    def test_catalogue_search(self):
        make_course(self.teacher, "Zebra Handling")
        make_course(self.teacher, "Giraffe Care")
        response = self.client.get(reverse("home"), {"q": "zebra"})
        self.assertContains(response, "Zebra Handling")
        self.assertNotContains(response, "Giraffe Care")


class InstructorDashboardTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.course = make_course(self.teacher, lessons=4)
        self.quiz = make_quiz(self.course, n_questions=2)
        self.alice, self.bob = make_user("alice", "learner"), make_user("bob", "learner")
        for who, n_done in [(self.alice, 3), (self.bob, 0)]:
            enrollment = enroll(who, self.course)
            for lesson in self.course.lessons.all()[:n_done]:
                LessonProgress.objects.create(enrollment=enrollment, lesson=lesson)
        self.client.force_login(self.alice)
        take = reverse("take_quiz", args=[self.course.pk])
        self.client.post(take, answers(self.quiz, 1))
        self.client.post(take, answers(self.quiz, 2))
        self.client.post(take, answers(self.quiz, 0))

    def test_dashboard_shows_progress_and_best_score(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("dashboard", args=[self.course.pk]))
        rows = {r["enrollment"].learner.username: r for r in response.context["rows"]}
        self.assertEqual((rows["alice"]["done"], rows["alice"]["best_score"], rows["alice"]["passed"]), (3, 100, True))
        self.assertEqual((rows["bob"]["done"], rows["bob"]["best_score"], rows["bob"]["passed"]), (0, None, False))
        self.assertContains(response, "3 of 4 (75%)")
        self.assertContains(response, "No attempts")

    def test_dashboard_query_count_does_not_grow_with_learners(self):
        self.client.force_login(self.teacher)
        url = reverse("dashboard", args=[self.course.pk])
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as before:
            self.client.get(url)
        for i in range(5):
            enroll(make_user(f"extra{i}", "learner"), self.course)
        with CaptureQueriesContext(connection) as after:
            self.client.get(url)
        self.assertEqual(len(before), len(after))

    def test_csv_export_and_formula_injection_guard(self):
        enroll(make_user("=cmd", "learner"), self.course)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("dashboard_csv", args=[self.course.pk]))
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0][0], "Learner")
        alice = next(r for r in rows if r[0] == "alice")
        self.assertEqual(alice[2:], ["3", "4", "75", "100", "yes"])
        self.assertTrue(any(r[0] == "'=cmd" for r in rows))


class QuestionFormTests(TestCase):
    def setUp(self):
        self.quiz = make_quiz(make_course(make_user("t", "instructor")), n_questions=0)

    def data(self, **over):
        base = {"text": "Q?", "choice_1": "a", "choice_2": "b", "choice_3": "", "choice_4": "", "correct": "1"}
        base.update(over)
        return base

    def test_valid_question_saves_exactly_one_correct_choice(self):
        form = QuestionForm(self.data(choice_3="c", correct="3"))
        self.assertTrue(form.is_valid(), form.errors)
        question = form.save(self.quiz)
        self.assertEqual(question.choices.count(), 3)
        self.assertEqual(list(question.choices.filter(is_correct=True).values_list("text", flat=True)), ["c"])

    def test_correct_answer_must_point_at_a_filled_option(self):
        self.assertFalse(QuestionForm(self.data(correct="4")).is_valid())

    def test_at_least_two_options_required(self):
        self.assertFalse(QuestionForm(self.data(choice_2="")).is_valid())

    def test_edit_replaces_choices(self):
        form = QuestionForm(self.data())
        form.is_valid()
        question = form.save(self.quiz)
        edit = QuestionForm(self.data(text="New?", choice_1="x", choice_2="y", correct="2"))
        edit.is_valid()
        edit.save(self.quiz, question)
        question.refresh_from_db()
        self.assertEqual(question.text, "New?")
        self.assertEqual([c.text for c in question.choices.all()], ["x", "y"])
        self.assertEqual(question.choices.get(is_correct=True).text, "y")

    def test_db_constraint_blocks_two_correct_choices(self):
        from django.db import IntegrityError, transaction
        question = Question.objects.create(quiz=self.quiz, text="q")
        Choice.objects.create(question=question, text="a", is_correct=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Choice.objects.create(question=question, text="b", is_correct=True)


class LessonOrderingTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.course = make_course(self.teacher, lessons=2)
        self.client.force_login(self.teacher)

    def test_new_lesson_defaults_to_next_position(self):
        response = self.client.get(reverse("lesson_create", args=[self.course.pk]))
        self.assertEqual(response.context["form"].initial["order"], 3)

    def test_duplicate_position_is_rejected(self):
        response = self.client.post(reverse("lesson_create", args=[self.course.pk]),
                                    {"title": "Dup", "content": "c", "order": 1})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already has position 1")
        self.assertFalse(Lesson.objects.filter(title="Dup").exists())

    def test_lessons_are_returned_in_order(self):
        Lesson.objects.create(course=self.course, title="Zero", content="c", order=0)
        titles = list(self.course.lessons.values_list("title", flat=True))
        self.assertEqual(titles[0], "Zero")

    def test_deleting_course_cascades(self):
        make_quiz(self.course)
        self.client.post(reverse("course_delete", args=[self.course.pk]))
        self.assertFalse(Course.objects.exists())
        self.assertFalse(Lesson.objects.exists())
        self.assertFalse(Question.objects.exists())


class AttachmentUploadTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.course = make_course(self.teacher, lessons=0)
        self.client.force_login(self.teacher)
        self.url = reverse("lesson_create", args=[self.course.pk])

    def post(self, upload):
        return self.client.post(self.url, {"title": "L", "content": "c", "order": 1, "attachment": upload})

    def test_oversized_attachment_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.post(SimpleUploadedFile("big.pdf", b"x" * (5 * 1024 * 1024 + 1)))
        self.assertContains(response, "5 MB or smaller")
        self.assertFalse(Lesson.objects.exists())

    def test_disallowed_extension_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.post(SimpleUploadedFile("evil.exe", b"MZ"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lesson.objects.exists())


class EndToEndWorkflowTests(TestCase):
    def test_full_flow_from_course_creation_to_dashboard(self):
        teacher = make_user("teacher", "instructor")
        self.client.force_login(teacher)
        self.client.post(reverse("course_create"), {"title": "Flow", "description": "d", "status": "draft"})
        course = Course.objects.get(title="Flow")
        for i in (1, 2):
            self.client.post(reverse("lesson_create", args=[course.pk]), {"title": f"L{i}", "content": "c", "order": i})
        self.client.post(reverse("quiz_edit", args=[course.pk]), {"title": "Final", "pass_mark": 50})
        for n in (1, 2):
            self.client.post(reverse("question_create", args=[course.pk]),
                             {"text": f"Q{n}", "choice_1": "right", "choice_2": "wrong", "correct": "1"})
        self.client.post(reverse("course_edit", args=[course.pk]), {"title": "Flow", "description": "d", "status": "published"})

        self.client.logout()
        self.client.post(reverse("signup"), {"username": "sam", "password1": "a-Strong-pass-77", "password2": "a-Strong-pass-77"})
        self.client.logout()
        self.assertTrue(self.client.login(username="sam", password="a-Strong-pass-77"))
        self.assertContains(self.client.get(reverse("home")), "Flow")
        self.client.post(reverse("enroll", args=[course.pk]))
        first = course.lessons.get(order=1)
        self.client.post(reverse("complete_lesson", args=[first.pk]))
        self.assertContains(self.client.get(reverse("my_courses")), "1 of 2 lessons done (50%)")

        quiz = course.quiz
        response = self.client.post(reverse("take_quiz", args=[course.pk]), answers(quiz, 1), follow=True)
        self.assertContains(response, "1 / 2")
        attempt = QuizAttempt.objects.get()
        self.assertEqual((attempt.correct, attempt.percent, attempt.passed), (1, 50, True))

        self.client.force_login(teacher)
        rows = self.client.get(reverse("dashboard", args=[course.pk])).context["rows"]
        self.assertEqual([(r["enrollment"].learner.username, r["done"], r["best_score"], r["passed"]) for r in rows],
                         [("sam", 1, 50, True)])
