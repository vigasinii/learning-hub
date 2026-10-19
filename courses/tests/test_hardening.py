import os
from io import StringIO
from unittest import mock

from django.core.exceptions import ValidationError
from django.contrib.messages import get_messages
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.forms import QuestionForm
from courses.models import (
    Choice, Course, Enrollment, Lesson, LessonProgress, Question, Quiz, QuizAttempt,
)

from .helpers import TempMediaMixin, answers, enroll, make_course, make_quiz, make_user


class IntegrityTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.learner = make_user("l", "learner")
        self.course = make_course(self.teacher, "A")
        self.other_course = make_course(self.teacher, "B")
        make_quiz(self.course)
        make_quiz(self.other_course)
        self.enrollment = enroll(self.learner, self.course)

    def test_deleting_an_instructor_with_courses_is_blocked(self):
        with self.assertRaises(ProtectedError):
            self.teacher.delete()
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_deleting_a_learner_removes_only_their_records(self):
        other = make_user("l2", "learner")
        enroll(other, self.course)
        self.learner.delete()
        self.assertEqual(Enrollment.objects.count(), 1)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())

    def test_progress_for_a_lesson_of_another_course_is_invalid(self):
        foreign = self.other_course.lessons.first()
        with self.assertRaises(ValidationError):
            LessonProgress(enrollment=self.enrollment, lesson=foreign).full_clean()
        LessonProgress(enrollment=self.enrollment, lesson=self.course.lessons.first()).full_clean()

    def test_attempt_for_a_quiz_of_another_course_is_invalid(self):
        bad = QuizAttempt(enrollment=self.enrollment, quiz=self.other_course.quiz, correct=1, total=3, percent=33, passed=False)
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_attempt_cannot_have_more_correct_than_total(self):
        bad = QuizAttempt(enrollment=self.enrollment, quiz=self.course.quiz, correct=4, total=3, percent=100, passed=True)
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_duplicate_enrolment_progress_and_position_blocked_by_database(self):
        from django.db import IntegrityError, transaction
        lesson = self.course.lessons.first()
        LessonProgress.objects.create(enrollment=self.enrollment, lesson=lesson)
        for make in (
            lambda: Enrollment.objects.create(learner=self.learner, course=self.course),
            lambda: LessonProgress.objects.create(enrollment=self.enrollment, lesson=lesson),
            lambda: Lesson.objects.create(course=self.course, title="dup", content="c", order=lesson.order),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                make()

    def test_question_save_is_all_or_nothing(self):
        quiz = Quiz.objects.create(course=make_course(self.teacher, "C"), title="Q", pass_mark=70)
        form = QuestionForm({"text": "Q?", "choice_1": "a", "choice_2": "b", "correct": "1"})
        self.assertTrue(form.is_valid())
        real_create = Choice.objects.create
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real_create(**kwargs)

        with mock.patch.object(Choice.objects, "create", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                form.save(quiz)
        self.assertEqual(Question.objects.filter(quiz=quiz).count(), 0)
        self.assertEqual(Choice.objects.filter(question__quiz=quiz).count(), 0)


class CrossUserAccessTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.course = make_course(self.teacher, lessons=2)
        self.quiz = make_quiz(self.course)
        self.alice, self.bob = make_user("alice", "learner"), make_user("bob", "learner")
        self.alice_enrollment = enroll(self.alice, self.course)
        enroll(self.bob, self.course)

    def test_one_learners_progress_never_shows_as_anothers(self):
        lesson = self.course.lessons.first()
        self.client.force_login(self.alice)
        self.client.post(reverse("complete_lesson", args=[lesson.pk]))
        self.client.force_login(self.bob)
        self.assertFalse(self.client.get(reverse("lesson_detail", args=[lesson.pk])).context["is_done"])
        self.assertContains(self.client.get(reverse("my_courses")), "0 of 2 lessons done (0%)")

    def test_answers_from_another_quiz_never_score(self):
        other_quiz = make_quiz(make_course(self.teacher, "Other"))
        foreign_correct = {f"question_{q.id}": q.choices.get(is_correct=True).id for q in other_quiz.questions.all()}
        mine = {f"question_{q.id}": foreign_correct[f"question_{other_quiz.questions.all()[i].id}"] for i, q in enumerate(self.quiz.questions.all())}
        self.client.force_login(self.alice)
        self.client.post(reverse("take_quiz", args=[self.course.pk]), mine)
        self.assertEqual(QuizAttempt.objects.get().correct, 0)

    def test_attempt_ids_are_scoped_to_the_logged_in_learner(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("take_quiz", args=[self.course.pk]), answers(self.quiz, 3))
        attempt = QuizAttempt.objects.get()
        url = reverse("quiz_result", args=[self.course.pk, attempt.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_attempt_id_cannot_be_used_under_a_different_course(self):
        other = make_course(self.teacher, "Other")
        self.client.force_login(self.alice)
        self.client.post(reverse("take_quiz", args=[self.course.pk]), answers(self.quiz, 3))
        attempt = QuizAttempt.objects.get()
        self.assertEqual(self.client.get(reverse("quiz_result", args=[other.pk, attempt.pk])).status_code, 404)


class AdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", "r@example.com", "pw-root-12345")
        self.teacher = make_user("t", "instructor")
        self.learner = make_user("l", "learner")

    def test_admin_is_closed_to_non_staff(self):
        for user in (self.teacher, self.learner):
            self.client.force_login(user)
            response = self.client.get(reverse("admin:index"))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response["Location"])
        self.client.logout()
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_superuser_can_open_every_registered_model_list(self):
        self.client.force_login(self.admin)
        make_quiz(make_course(self.teacher))
        for name in ["accounts_user", "courses_course", "courses_lesson", "courses_enrollment", "courses_lessonprogress",
                     "courses_quiz", "courses_question", "courses_quizattempt"]:
            try:
                url = reverse(f"admin:{name}_changelist")
            except Exception:
                continue
            self.assertEqual(self.client.get(url).status_code, 200, name)

    def test_admin_can_promote_a_user_to_instructor(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("admin:accounts_user_changelist"),
            {"action": "make_instructor", "_selected_action": [self.learner.pk]},
        )
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.role, "instructor")
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("instructor_courses")).status_code, 200)

    def test_admin_can_create_instructor_via_role_field(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertContains(response, 'name="role"')

    def _question_post(self, quiz, **choices):
        data = {
            "quiz": quiz.pk, "text": "Q?", "order": 1,
            "choices-TOTAL_FORMS": 2, "choices-INITIAL_FORMS": 0,
            "choices-MIN_NUM_FORMS": 0, "choices-MAX_NUM_FORMS": 1000,
        }
        data.update(choices)
        return self.client.post(reverse("admin:courses_question_add"), data)

    def test_admin_question_needs_exactly_one_correct_option(self):
        self.client.force_login(self.admin)
        quiz = make_quiz(make_course(self.teacher), n_questions=0)
        none_correct = self._question_post(quiz, **{"choices-0-text": "a", "choices-1-text": "b"})
        both_correct = self._question_post(quiz, **{"choices-0-text": "a", "choices-0-is_correct": "on",
                                                    "choices-1-text": "b", "choices-1-is_correct": "on"})
        one_option = self._question_post(quiz, **{"choices-0-text": "a", "choices-0-is_correct": "on"})
        for response in (none_correct, both_correct, one_option):
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Question.objects.filter(quiz=quiz).exists())

    def test_admin_valid_question_saves(self):
        self.client.force_login(self.admin)
        quiz = make_quiz(make_course(self.teacher), n_questions=0)
        response = self._question_post(quiz, **{"choices-0-text": "a", "choices-0-is_correct": "on", "choices-1-text": "b"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Question.objects.get(quiz=quiz).choices.filter(is_correct=True).count(), 1)


class InstructorDemotionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", "r@example.com", "pw-root-12345")
        self.owner = make_user("owner", "instructor")
        make_course(self.owner, "One")
        make_course(self.owner, "Two")
        self.idle = make_user("idle", "instructor")
        self.learner = make_user("plain", "learner")
        self.client.force_login(self.admin)

    def run_action(self, *users):
        return self.client.post(
            reverse("admin:accounts_user_changelist"),
            {"action": "make_learner", "_selected_action": [u.pk for u in users]},
            follow=True,
        )

    def roles(self):
        return {u.username: User.objects.get(pk=u.pk).role for u in (self.owner, self.idle, self.learner)}

    def test_bulk_action_demotes_only_eligible_users(self):
        response = self.run_action(self.owner, self.idle, self.learner)
        self.assertEqual(self.roles(), {"owner": "instructor", "idle": "learner", "plain": "learner"})
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("1 user(s) are now learners" in t or "2 user(s) are now learners" in t for t in texts))
        warning = next(t for t in texts if "Not changed" in t)
        self.assertEqual(warning.count("owner"), 1)
        self.assertNotIn("idle", warning)

    def test_blocked_instructor_keeps_courses_reachable(self):
        self.run_action(self.owner)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("instructor_courses")).status_code, 200)
        self.assertEqual(Course.objects.filter(instructor=self.owner).count(), 2)

    def test_eligible_only_selection_shows_no_warning(self):
        response = self.run_action(self.idle)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertFalse(any("Not changed" in t for t in texts))
        self.assertEqual(self.roles()["idle"], "learner")

    def test_demotion_allowed_once_courses_are_deleted(self):
        Course.objects.filter(instructor=self.owner).delete()
        self.run_action(self.owner)
        self.assertEqual(self.roles()["owner"], "learner")

    def test_demotion_allowed_once_courses_are_reassigned(self):
        Course.objects.filter(instructor=self.owner).update(instructor=self.idle)
        self.run_action(self.owner)
        self.assertEqual(self.roles()["owner"], "learner")
        self.assertEqual(Course.objects.filter(instructor=self.idle).count(), 2)

    def test_model_validation_blocks_demotion_through_the_admin_edit_form(self):
        self.owner.role = "learner"
        with self.assertRaises(ValidationError) as ctx:
            self.owner.full_clean(exclude=["password"])
        self.assertIn("role", ctx.exception.message_dict)
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[self.owner.pk]),
            {"username": "owner", "role": "learner", "is_active": "on",
             "date_joined_0": "2026-01-01", "date_joined_1": "10:00:00"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "still owns courses")
        self.assertEqual(self.roles()["owner"], "instructor")

    def test_admin_edit_form_allows_demoting_an_eligible_user(self):
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[self.idle.pk]),
            {"username": "idle", "role": "learner", "is_active": "on",
             "date_joined_0": "2026-01-01", "date_joined_1": "10:00:00"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.roles()["idle"], "learner")

    def test_promotion_is_unaffected(self):
        self.owner.role = "instructor"
        self.owner.full_clean(exclude=["password"])


class AttachmentLifecycleTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.course = make_course(self.teacher, lessons=1)
        self.lesson = self.course.lessons.first()
        self.lesson.attachment.save("first.txt", ContentFile(b"one"), save=True)
        self.first_path = self.lesson.attachment.path

    def test_file_exists_after_upload(self):
        self.assertTrue(os.path.exists(self.first_path))

    def test_deleting_a_lesson_removes_its_file(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.lesson.delete()
        self.assertFalse(os.path.exists(self.first_path))

    def test_deleting_a_course_removes_all_lesson_files(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.course.delete()
        self.assertFalse(os.path.exists(self.first_path))

    def test_replacing_an_attachment_removes_the_old_file(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.lesson.attachment.save("second.txt", ContentFile(b"two"), save=True)
        self.assertFalse(os.path.exists(self.first_path))
        self.assertTrue(os.path.exists(self.lesson.attachment.path))

    def test_saving_without_changing_the_file_keeps_it(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.lesson.title = "renamed"
            self.lesson.save()
        self.assertTrue(os.path.exists(self.first_path))

    def test_clearing_the_attachment_in_the_edit_form_removes_the_file(self):
        self.client.force_login(self.teacher)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("lesson_edit", args=[self.course.pk, self.lesson.pk]),
                {"title": "L", "content": "c", "order": 1, "attachment-clear": "on"},
            )
        self.assertEqual(response.status_code, 302)
        self.lesson.refresh_from_db()
        self.assertFalse(self.lesson.attachment)
        self.assertFalse(os.path.exists(self.first_path))

    def test_download_after_deletion_is_404_not_500(self):
        learner = make_user("l", "learner")
        enroll(learner, self.course)
        url = reverse("lesson_attachment", args=[self.lesson.pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.lesson.attachment.delete(save=True)
        self.client.force_login(learner)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_download_when_file_missing_from_disk_is_404_not_500(self):
        learner = make_user("l", "learner")
        enroll(learner, self.course)
        os.remove(self.first_path)
        self.client.force_login(learner)
        self.assertEqual(self.client.get(reverse("lesson_attachment", args=[self.lesson.pk])).status_code, 404)

    def test_download_is_forced_attachment(self):
        learner = make_user("l", "learner")
        enroll(learner, self.course)
        self.client.force_login(learner)
        response = self.client.get(reverse("lesson_attachment", args=[self.lesson.pk]))
        self.assertIn("attachment", response["Content-Disposition"])
        response.close()


class InstructorWorkflowTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.learner = make_user("l", "learner")
        self.client.force_login(self.teacher)

    def test_create_publish_and_learner_discovers_course(self):
        response = self.client.post(reverse("course_create"), {"title": "New", "description": "d", "status": "draft"})
        course = Course.objects.get(title="New")
        self.assertRedirects(response, reverse("manage_course", args=[course.pk]))
        self.assertEqual(course.instructor, self.teacher)
        self.client.force_login(self.learner)
        self.assertNotContains(self.client.get(reverse("home")), "New")
        self.client.force_login(self.teacher)
        self.client.post(reverse("course_edit", args=[course.pk]), {"title": "New", "description": "d", "status": "published"})
        self.client.force_login(self.learner)
        self.assertContains(self.client.get(reverse("home")), "New")

    def test_course_form_rejects_invalid_status_and_blank_title(self):
        response = self.client.post(reverse("course_create"), {"title": "", "description": "d", "status": "published"})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("course_create"), {"title": "x", "description": "d", "status": "hacked"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.exists())

    def test_cannot_set_another_instructor_as_owner_by_posting_the_field(self):
        other = make_user("t2", "instructor")
        self.client.post(reverse("course_create"), {"title": "Mine", "description": "d", "status": "draft", "instructor": other.pk})
        self.assertEqual(Course.objects.get(title="Mine").instructor, self.teacher)

    def test_lesson_create_edit_delete(self):
        course = make_course(self.teacher, lessons=0)
        self.client.post(reverse("lesson_create", args=[course.pk]), {"title": "L1", "content": "c", "order": 1})
        lesson = course.lessons.get()
        self.client.post(reverse("lesson_edit", args=[course.pk, lesson.pk]), {"title": "L1b", "content": "c", "order": 1})
        lesson.refresh_from_db()
        self.assertEqual(lesson.title, "L1b")
        self.client.post(reverse("lesson_delete", args=[course.pk, lesson.pk]))
        self.assertFalse(course.lessons.exists())

    def test_lesson_cannot_be_moved_to_another_course_via_post(self):
        mine, theirs = make_course(self.teacher, "Mine", lessons=0), make_course(make_user("t2", "instructor"), "Theirs", lessons=0)
        self.client.post(reverse("lesson_create", args=[mine.pk]), {"title": "L", "content": "c", "order": 1, "course": theirs.pk})
        self.assertEqual(mine.lessons.count(), 1)
        self.assertEqual(theirs.lessons.count(), 0)

    def test_dangerous_video_url_scheme_is_rejected(self):
        course = make_course(self.teacher, lessons=0)
        response = self.client.post(
            reverse("lesson_create", args=[course.pk]),
            {"title": "L", "content": "c", "order": 1, "video_url": "javascript:alert(1)"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(course.lessons.exists())

    def test_lesson_content_is_html_escaped_for_learners(self):
        course = make_course(self.teacher, lessons=0)
        Lesson.objects.create(course=course, title="x", content="<script>alert(1)</script>", order=1)
        enroll(self.learner, course)
        self.client.force_login(self.learner)
        response = self.client.get(reverse("lesson_detail", args=[course.lessons.get().pk]))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_quiz_builder_flow_and_validation(self):
        course = make_course(self.teacher)
        settings_url = reverse("quiz_edit", args=[course.pk])
        for bad in (0, 101):
            self.assertEqual(self.client.post(settings_url, {"title": "Q", "pass_mark": bad}).status_code, 200)
        self.assertFalse(Quiz.objects.exists())
        self.client.post(settings_url, {"title": "Q", "pass_mark": 80})
        quiz = Quiz.objects.get()
        self.assertEqual((quiz.course, quiz.pass_mark), (course, 80))
        add = reverse("question_create", args=[course.pk])
        self.assertEqual(self.client.post(add, {"text": "t", "choice_1": "a", "choice_2": "b", "correct": "3"}).status_code, 200)
        self.client.post(add, {"text": "t", "choice_1": "a", "choice_2": "b", "correct": "2"})
        question = quiz.questions.get()
        self.assertEqual(question.choices.get(is_correct=True).text, "b")
        self.client.post(settings_url, {"title": "Q2", "pass_mark": 60})
        self.assertEqual(Quiz.objects.count(), 1)
        self.client.post(reverse("question_delete", args=[course.pk, question.pk]))
        self.assertFalse(quiz.questions.exists())

    def test_learner_cannot_take_a_quiz_that_has_no_questions(self):
        course = make_course(self.teacher)
        Quiz.objects.create(course=course, title="Empty", pass_mark=70)
        enroll(self.learner, course)
        self.client.force_login(self.learner)
        response = self.client.post(reverse("take_quiz", args=[course.pk]), {})
        self.assertRedirects(response, reverse("course_detail", args=[course.pk]))
        self.assertFalse(QuizAttempt.objects.exists())

    def test_quiz_pass_threshold_through_the_view(self):
        course = make_course(self.teacher)
        quiz = make_quiz(course, pass_mark=67, n_questions=3)
        enroll(self.learner, course)
        self.client.force_login(self.learner)
        url = reverse("take_quiz", args=[course.pk])
        self.client.post(url, answers(quiz, 2))
        self.client.post(url, answers(quiz, 3))
        first, second = QuizAttempt.objects.order_by("id")
        self.assertEqual((first.percent, first.passed), (67, False))
        self.assertTrue(second.passed)


class SeedDemoTests(TestCase):
    def run_seed(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        return out.getvalue()

    def counts(self):
        return tuple(m.objects.count() for m in (User, Course, Lesson, Quiz, Question, Choice, Enrollment, LessonProgress))

    def test_empty_database_gets_expected_demo_data(self):
        self.run_seed()
        self.assertEqual(self.counts(), (3, 2, 4, 1, 3, 10, 2, 2))
        self.assertEqual(User.objects.get(username="instructor1").role, "instructor")
        course = Course.objects.get(title="E-filing for Court Clerks")
        self.assertTrue(course.is_published)
        self.assertEqual(Course.objects.get(title__startswith="Draft").status, "draft")
        self.assertTrue(User.objects.get(username="learner1").check_password("demo-pass-123"))
        self.assertEqual(Course.objects.get(pk=course.pk).enrollments.get(learner__username="learner1").progress.count(), 2)

    def test_running_twice_creates_no_duplicates(self):
        self.run_seed()
        first = self.counts()
        self.run_seed()
        self.assertEqual(self.counts(), first)

    def test_partial_data_is_repaired_without_duplicates(self):
        self.run_seed()
        Lesson.objects.filter(order__in=(3, 4)).delete()
        Question.objects.filter(text__startswith="Where").delete()
        self.run_seed()
        self.assertEqual(self.counts(), (3, 2, 4, 1, 3, 10, 2, 2))

    def test_user_created_by_hand_is_not_modified_and_real_data_survives(self):
        real_teacher = make_user("real_teacher", "instructor")
        real_course = make_course(real_teacher, "Real course")
        make_user("learner1", "learner")
        self.run_seed()
        self.assertFalse(User.objects.get(username="learner1").check_password("demo-pass-123"))
        self.assertTrue(Course.objects.filter(pk=real_course.pk).exists())
        self.assertEqual(real_course.lessons.count(), 3)

    def test_conflicting_existing_account_aborts_without_changes(self):
        make_user("instructor1", "learner")
        before = self.counts()
        with self.assertRaises(CommandError):
            self.run_seed()
        self.assertEqual(self.counts(), before)
        self.assertEqual(User.objects.get(username="instructor1").role, "learner")

    def test_demo_learner_can_log_in_and_instructor_sees_dashboard(self):
        self.run_seed()
        self.assertTrue(self.client.login(username="learner1", password="demo-pass-123"))
        self.assertContains(self.client.get(reverse("my_courses")), "2 of 4 lessons done (50%)")
        self.client.logout()
        self.client.login(username="instructor1", password="demo-pass-123")
        course = Course.objects.get(title="E-filing for Court Clerks")
        self.assertContains(self.client.get(reverse("dashboard", args=[course.pk])), "learner2")


class SeedDemoExistingDataTests(TestCase):
    def setUp(self):
        call_command("seed_demo", stdout=StringIO())
        self.course = Course.objects.get(title="E-filing for Court Clerks")
        self.learner1 = User.objects.get(username="learner1")
        self.learner2 = User.objects.get(username="learner2")

    def reseed(self):
        call_command("seed_demo", stdout=StringIO())

    def test_rerun_with_existing_demo_course_keeps_real_progress_and_attempts(self):
        enrollment1 = Enrollment.objects.get(learner=self.learner1, course=self.course)
        LessonProgress.objects.create(enrollment=enrollment1, lesson=self.course.lessons.get(order=3))
        enrollment2 = Enrollment.objects.get(learner=self.learner2, course=self.course)
        attempt = QuizAttempt.objects.create(
            enrollment=enrollment2, quiz=self.course.quiz, correct=2, total=3, percent=67, passed=False
        )
        self.reseed()
        self.assertEqual(enrollment1.progress.count(), 3)
        self.assertTrue(QuizAttempt.objects.filter(pk=attempt.pk).exists())
        self.assertEqual(Course.objects.filter(title="E-filing for Court Clerks").count(), 1)

    def test_instructor_edits_and_additions_survive_a_rerun(self):
        lesson = self.course.lessons.get(order=1)
        lesson.title = "Edited by instructor"
        lesson.save()
        Lesson.objects.create(course=self.course, title="Extra", content="c", order=5)
        extra_q = Question.objects.create(quiz=self.course.quiz, text="Instructor question", order=4)
        Choice.objects.create(question=extra_q, text="yes", is_correct=True)
        self.course.quiz.pass_mark = 90
        self.course.quiz.save()
        self.reseed()
        lesson.refresh_from_db()
        self.assertEqual(lesson.title, "Edited by instructor")
        self.assertEqual(self.course.lessons.count(), 5)
        self.assertEqual(self.course.quiz.questions.count(), 4)
        self.course.quiz.refresh_from_db()
        self.assertEqual(self.course.quiz.pass_mark, 90)

    def test_missing_quiz_is_recreated_with_questions_and_choices(self):
        self.course.quiz.delete()
        self.reseed()
        quiz = Course.objects.get(pk=self.course.pk).quiz
        self.assertEqual(quiz.questions.count(), 3)
        for question in quiz.questions.all():
            self.assertEqual(question.choices.filter(is_correct=True).count(), 1)
            self.assertGreaterEqual(question.choices.count(), 2)

    def test_question_without_choices_gets_its_choices_back(self):
        question = self.course.quiz.questions.get(text__startswith="Which file format")
        question.choices.all().delete()
        self.reseed()
        self.assertEqual(question.choices.count(), 4)
        self.assertEqual(question.choices.get(is_correct=True).text, "PDF")

    def test_question_that_still_has_some_choices_is_left_alone(self):
        question = self.course.quiz.questions.get(text__startswith="Which file format")
        question.choices.exclude(text="PDF").delete()
        self.reseed()
        self.assertEqual(question.choices.count(), 1)

    def test_missing_lessons_and_draft_course_are_recreated(self):
        self.course.lessons.filter(order__in=(2, 4)).delete()
        Course.objects.get(title__startswith="Draft").delete()
        self.reseed()
        self.assertEqual(list(self.course.lessons.values_list("order", flat=True)), [1, 2, 3, 4])
        self.assertTrue(Course.objects.filter(title__startswith="Draft").exists())

    def test_missing_enrolment_is_recreated_without_touching_the_other(self):
        Enrollment.objects.filter(learner=self.learner2).delete()
        self.reseed()
        self.assertTrue(Enrollment.objects.filter(learner=self.learner2, course=self.course).exists())
        self.assertEqual(Enrollment.objects.count(), 2)

    def test_changed_demo_passwords_are_not_reset(self):
        self.learner1.set_password("my-own-password")
        self.learner1.save()
        self.reseed()
        self.learner1.refresh_from_db()
        self.assertTrue(self.learner1.check_password("my-own-password"))


class RoleRestrictedRelationTests(TestCase):
    def test_course_owner_must_be_an_instructor(self):
        course = Course(instructor=make_user("l", "learner"), title="x", description="d")
        with self.assertRaises(ValidationError) as ctx:
            course.full_clean()
        self.assertIn("instructor", ctx.exception.message_dict)

    def test_enrolled_user_must_be_a_learner(self):
        course = make_course(make_user("t", "instructor"))
        with self.assertRaises(ValidationError) as ctx:
            Enrollment(learner=make_user("t2", "instructor"), course=course).full_clean()
        self.assertIn("learner", ctx.exception.message_dict)
