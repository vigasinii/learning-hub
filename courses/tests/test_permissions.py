from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from courses.models import Course, Enrollment, LessonProgress, QuizAttempt

from .helpers import TempMediaMixin, answers, enroll, make_course, make_quiz, make_user


class PermissionTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.owner = make_user("owner", "instructor")
        self.other_instructor = make_user("other", "instructor")
        self.learner = make_user("learner", "learner")
        self.published = make_course(self.owner, "Published")
        self.draft = make_course(self.owner, "Draft", status=Course.Status.DRAFT)
        self.quiz = make_quiz(self.published)

    def test_anonymous_users_are_redirected_to_login(self):
        for name, args in [("home", []), ("my_courses", []), ("instructor_courses", []),
                           ("course_detail", [self.published.pk]), ("take_quiz", [self.published.pk])]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("/accounts/login/", response["Location"], name)

    def test_learner_cannot_create_course(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("course_create")).status_code, 403)
        response = self.client.post(reverse("course_create"), {"title": "x", "description": "y", "status": "published"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Course.objects.filter(title="x").exists())

    def test_learner_cannot_edit_delete_or_manage_course(self):
        self.client.force_login(self.learner)
        for name in ["course_edit", "course_delete", "manage_course", "dashboard", "lesson_create", "quiz_edit"]:
            self.assertEqual(self.client.get(reverse(name, args=[self.published.pk])).status_code, 403, name)
        self.assertEqual(self.client.post(reverse("course_delete", args=[self.published.pk])).status_code, 403)
        self.assertTrue(Course.objects.filter(pk=self.published.pk).exists())

    def test_instructor_cannot_touch_another_instructors_course(self):
        self.client.force_login(self.other_instructor)
        pk = self.published.pk
        lesson = self.published.lessons.first()
        question = self.quiz.questions.first()
        checks = [
            ("manage_course", [pk]), ("course_edit", [pk]), ("course_delete", [pk]), ("dashboard", [pk]),
            ("dashboard_csv", [pk]), ("lesson_create", [pk]), ("lesson_edit", [pk, lesson.pk]),
            ("lesson_delete", [pk, lesson.pk]), ("quiz_manage", [pk]), ("quiz_edit", [pk]),
            ("question_create", [pk]), ("question_edit", [pk, question.pk]), ("question_delete", [pk, question.pk]),
        ]
        for name, args in checks:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 404, name)

    def test_other_instructor_cannot_modify_via_post(self):
        self.client.force_login(self.other_instructor)
        self.client.post(reverse("course_edit", args=[self.published.pk]),
                         {"title": "Hacked", "description": "d", "status": "draft"})
        self.client.post(reverse("course_delete", args=[self.published.pk]))
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, "Published")

    def test_owner_can_edit_own_course(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("course_edit", args=[self.published.pk]),
                                    {"title": "Renamed", "description": "d", "status": "published"})
        self.assertEqual(response.status_code, 302)
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, "Renamed")

    def test_owner_cannot_edit_lesson_of_another_course_via_url_tampering(self):
        other_course = make_course(self.other_instructor, "Theirs")
        foreign_lesson = other_course.lessons.first()
        self.client.force_login(self.owner)
        url = reverse("lesson_edit", args=[self.published.pk, foreign_lesson.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_instructor_cannot_enrol_or_take_quizzes(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("enroll", args=[self.published.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("take_quiz", args=[self.published.pk])).status_code, 403)

    def test_draft_not_in_catalogue(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Published")
        self.assertNotContains(response, "Draft")

    def test_draft_urls_return_404_for_learner(self):
        self.client.force_login(self.learner)
        lesson = self.draft.lessons.first()
        make_quiz(self.draft)
        self.assertEqual(self.client.get(reverse("course_detail", args=[self.draft.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("enroll", args=[self.draft.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("take_quiz", args=[self.draft.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("lesson_detail", args=[lesson.pk])).status_code, 404)
        self.assertFalse(Enrollment.objects.exists())

    def test_course_unpublished_after_enrolment_is_hidden_again(self):
        enroll(self.learner, self.published)
        self.published.status = Course.Status.DRAFT
        self.published.save()
        self.client.force_login(self.learner)
        lesson = self.published.lessons.first()
        self.assertEqual(self.client.get(reverse("lesson_detail", args=[lesson.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("take_quiz", args=[self.published.pk])).status_code, 404)

    def test_cannot_take_quiz_without_enrolment(self):
        self.client.force_login(self.learner)
        url = reverse("take_quiz", args=[self.published.pk])
        self.assertRedirects(self.client.get(url), reverse("course_detail", args=[self.published.pk]))
        self.client.post(url, answers(self.quiz, 3))
        self.assertEqual(QuizAttempt.objects.count(), 0)

    def test_can_take_quiz_once_enrolled(self):
        enroll(self.learner, self.published)
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("take_quiz", args=[self.published.pk])).status_code, 200)

    def test_cannot_read_or_complete_lessons_without_enrolment(self):
        self.client.force_login(self.learner)
        lesson = self.published.lessons.first()
        self.assertEqual(self.client.get(reverse("lesson_detail", args=[lesson.pk])).status_code, 302)
        self.client.post(reverse("complete_lesson", args=[lesson.pk]))
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_enrolment_in_one_course_does_not_unlock_another(self):
        other_course = make_course(self.owner, "Other")
        make_quiz(other_course)
        enroll(self.learner, self.published)
        self.client.force_login(self.learner)
        self.client.post(reverse("take_quiz", args=[other_course.pk]), {})
        self.assertEqual(QuizAttempt.objects.count(), 0)

    def test_state_changing_views_reject_get(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("enroll", args=[self.published.pk])).status_code, 405)
        lesson = self.published.lessons.first()
        self.assertEqual(self.client.get(reverse("complete_lesson", args=[lesson.pk])).status_code, 405)

    def test_csrf_is_enforced(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.learner)
        response = strict.post(reverse("enroll", args=[self.published.pk]))
        self.assertEqual(response.status_code, 403)

    def test_attachment_download_rules(self):
        lesson = self.published.lessons.first()
        lesson.attachment.save("notes.txt", SimpleUploadedFile("notes.txt", b"secret"), save=True)
        url = reverse("lesson_attachment", args=[lesson.pk])
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(url).status_code, 404)
        enroll(self.learner, self.published)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"secret")
        response.close()
        self.client.force_login(self.other_instructor)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        owner_response = self.client.get(url)
        self.assertEqual(owner_response.status_code, 200)
        owner_response.close()
        lesson.attachment.delete(save=False)
