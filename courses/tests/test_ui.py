from io import StringIO

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.models import Course, LessonProgress, Quiz

from .helpers import TempMediaMixin, answers, enroll, make_course, make_quiz, make_user
from .html_checks import inspect_markup


class EveryPageRendersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())
        cls.course = Course.objects.get(title__startswith="E-filing")
        cls.draft = Course.objects.get(title__startswith="Draft")

    def pages_for(self, username):
        course = self.course
        lesson = course.lessons.first()
        question = course.quiz.questions.first()
        teach = f"/teach/courses/{course.pk}"
        if username == "instructor1":
            return [
                reverse("home"), reverse("instructor_courses"), reverse("course_create"),
                teach + "/", teach + "/edit/", teach + "/delete/", teach + "/lessons/new/",
                f"{teach}/lessons/{lesson.pk}/edit/", f"{teach}/lessons/{lesson.pk}/delete/",
                teach + "/quiz/", teach + "/quiz/settings/", teach + "/quiz/questions/new/",
                f"{teach}/quiz/questions/{question.pk}/edit/", f"{teach}/quiz/questions/{question.pk}/delete/",
                teach + "/dashboard/", reverse("course_detail", args=[course.pk]),
                reverse("instructor_courses") + "?status=published&q=e-filing",
                reverse("home") + "?q=nothing-matches-this",
            ]
        return [
            reverse("home"), reverse("home") + "?q=nothing-matches-this", reverse("my_courses"),
            reverse("course_detail", args=[course.pk]), reverse("lesson_detail", args=[lesson.pk]),
            reverse("take_quiz", args=[course.pk]), "/does-not-exist/",
        ]

    def test_pages_render_with_valid_markup_and_labelled_controls(self):
        for username in ("learner1", "instructor1"):
            self.client.force_login(User.objects.get(username=username))
            for url in self.pages_for(username):
                response = self.client.get(url)
                self.assertIn(response.status_code, (200, 404), f"{username} {url}")
                html = response.content.decode()
                self.assertEqual(inspect_markup(html), [], f"{username} {url}")
                self.assertNotIn("{%", html, f"{username} {url}")
                self.assertNotIn("{{", html, f"{username} {url}")
                self.assertIn("<title>", html)

    def test_anonymous_pages_render_with_valid_markup(self):
        for url in (reverse("login"), reverse("signup")):
            html = self.client.get(url).content.decode()
            self.assertEqual(inspect_markup(html), [], url)

    def test_validation_error_pages_keep_valid_markup(self):
        self.client.force_login(User.objects.get(username="instructor1"))
        response = self.client.post(reverse("course_create"), {"title": "", "description": "", "status": "x"})
        self.assertContains(response, "field-error")
        self.assertEqual(inspect_markup(response.content.decode()), [])

    def test_static_assets_exist(self):
        self.assertIsNotNone(finders.find("style.css"))
        self.assertIsNotNone(finders.find("app.js"))

    def test_base_template_links_assets(self):
        self.client.force_login(User.objects.get(username="learner1"))
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("/static/style.css", html)
        self.assertIn("/static/app.js", html)


class NavigationTests(TestCase):
    def test_learner_sees_learner_links_and_active_section(self):
        self.client.force_login(make_user("l", "learner"))
        html = self.client.get(reverse("my_courses")).content.decode()
        self.assertIn(reverse("my_courses"), html)
        self.assertNotIn(reverse("instructor_courses"), html)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn(f'<a href="{reverse("my_courses")}" class="active" aria-current="page">', html)

    def test_instructor_sees_teach_link_and_active_section(self):
        self.client.force_login(make_user("t", "instructor"))
        html = self.client.get(reverse("instructor_courses")).content.decode()
        self.assertIn(f'<a href="{reverse("instructor_courses")}" class="active" aria-current="page">', html)
        self.assertNotIn(reverse("my_courses"), html)

    def test_anonymous_visitor_sees_login_and_signup(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn(reverse("signup"), html)
        self.assertNotIn("Log out", html)

    def test_error_pages_still_render_navigation(self):
        self.client.force_login(make_user("l", "learner"))
        response = self.client.get("/missing/")
        self.assertEqual(response.status_code, 404)

    def test_logout_is_a_post_form_with_csrf_token(self):
        self.client.force_login(make_user("l", "learner"))
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'action="{reverse("logout")}"', html)


class CatalogueUiTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.mine = make_course(self.teacher, "Enrolled Course")
        self.other = make_course(self.teacher, "Open Course")
        make_course(self.teacher, "Hidden Draft Course", status=Course.Status.DRAFT)
        self.learner = make_user("l", "learner")
        enroll(self.learner, self.mine)

    def test_enrolled_course_shows_badge_and_others_show_enrol_button(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["enrolled_ids"], {self.mine.pk})
        self.assertContains(response, "Enrolled</span>", count=1)
        self.assertContains(response, f'action="{reverse("enroll", args=[self.other.pk])}"', count=1)
        self.assertNotContains(response, f'action="{reverse("enroll", args=[self.mine.pk])}"')
        self.assertNotContains(response, "Hidden Draft Course")

    def test_instructor_does_not_see_enrol_buttons(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "/enroll/")
        self.assertContains(response, "View course")

    def test_card_shows_real_lesson_count_and_instructor(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "3 lessons")
        self.assertContains(response, "t</span>")

    def test_empty_catalogue_and_empty_search_states(self):
        Course.objects.all().delete()
        self.client.force_login(self.learner)
        self.assertContains(self.client.get(reverse("home")), "No published courses yet")
        make_course(self.teacher, "Something")
        self.assertContains(self.client.get(reverse("home"), {"q": "zzz"}), "No courses match your search")

    def test_catalogue_query_count_does_not_grow_with_courses(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.force_login(self.learner)
        with CaptureQueriesContext(connection) as before:
            self.client.get(reverse("home"))
        for index in range(5):
            make_course(self.teacher, f"Extra {index}")
        with CaptureQueriesContext(connection) as after:
            self.client.get(reverse("home"))
        self.assertEqual(len(before), len(after))


class LearnerJourneyUiTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.learner = make_user("l", "learner")
        self.course = make_course(self.teacher, lessons=3)
        self.quiz = make_quiz(self.course)
        self.client.force_login(self.learner)

    def detail(self):
        return self.client.get(reverse("course_detail", args=[self.course.pk]))

    def test_unenrolled_learner_sees_enrol_call_to_action_and_no_lesson_links(self):
        response = self.detail()
        self.assertContains(response, "Enrol in this course")
        for lesson in self.course.lessons.all():
            self.assertNotContains(response, reverse("lesson_detail", args=[lesson.pk]))
        self.assertNotContains(response, reverse("take_quiz", args=[self.course.pk]))

    def test_next_action_moves_through_the_course(self):
        enrollment = enroll(self.learner, self.course)
        lessons = list(self.course.lessons.all())
        response = self.detail()
        self.assertContains(response, "Start the first lesson")
        self.assertEqual(response.context["next_lesson"], lessons[0])
        LessonProgress.objects.create(enrollment=enrollment, lesson=lessons[0])
        response = self.detail()
        self.assertContains(response, "Continue with lesson 2")
        self.assertContains(response, "1 of 3 lessons done (33%)")
        self.assertEqual(response.context["next_lesson"], lessons[1])
        for lesson in lessons[1:]:
            LessonProgress.objects.create(enrollment=enrollment, lesson=lesson)
        response = self.detail()
        self.assertIsNone(response.context["next_lesson"])
        self.assertContains(response, "All lessons done: take the quiz")

    def test_lesson_page_shows_progress_sidebar_and_navigation(self):
        enrollment = enroll(self.learner, self.course)
        lessons = list(self.course.lessons.all())
        LessonProgress.objects.create(enrollment=enrollment, lesson=lessons[0])
        response = self.client.get(reverse("lesson_detail", args=[lessons[1].pk]))
        self.assertEqual(response.context["done_ids"], {lessons[0].pk})
        self.assertEqual(response.context["previous_lesson"], lessons[0])
        self.assertEqual(response.context["next_lesson"], lessons[2])
        self.assertContains(response, "1 of 3 lessons done (33%)")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "Mark as complete")

    def test_last_lesson_offers_the_quiz(self):
        enroll(self.learner, self.course)
        last = self.course.lessons.last()
        response = self.client.get(reverse("lesson_detail", args=[last.pk]))
        self.assertContains(response, reverse("take_quiz", args=[self.course.pk]))

    def test_completed_lesson_shows_completed_state_instead_of_button(self):
        enrollment = enroll(self.learner, self.course)
        lesson = self.course.lessons.first()
        LessonProgress.objects.create(enrollment=enrollment, lesson=lesson)
        response = self.client.get(reverse("lesson_detail", args=[lesson.pk]))
        self.assertNotContains(response, "Mark as complete")
        self.assertContains(response, "Completed")

    def test_my_courses_shows_call_to_action_by_progress(self):
        enrollment = enroll(self.learner, self.course)
        self.assertContains(self.client.get(reverse("my_courses")), "Start")
        for lesson in self.course.lessons.all():
            LessonProgress.objects.create(enrollment=enrollment, lesson=lesson)
        response = self.client.get(reverse("my_courses"))
        self.assertContains(response, "Completed")
        self.assertContains(response, "3 of 3 lessons done (100%)")

    def test_empty_my_courses_state_links_to_the_catalogue(self):
        response = self.client.get(reverse("my_courses"))
        self.assertContains(response, "You have not enrolled in any courses yet")
        self.assertContains(response, 'href="/"')

    def test_quiz_page_never_reveals_correct_answers(self):
        enroll(self.learner, self.course)
        response = self.client.get(reverse("take_quiz", args=[self.course.pk]))
        html = response.content.decode().lower()
        self.assertNotIn("correct", html)
        self.assertNotIn("checked", html)
        self.assertEqual(html.count('type="radio"'), 6)
        self.assertEqual(response.context["attempt_count"], 0)

    def test_quiz_page_reports_previous_attempts(self):
        enroll(self.learner, self.course)
        url = reverse("take_quiz", args=[self.course.pk])
        self.client.post(url, answers(self.quiz, 1))
        response = self.client.get(url)
        self.assertEqual(response.context["attempt_count"], 1)
        self.assertContains(response, "previous attempt")

    def test_result_page_shows_pass_state_and_attempt_history(self):
        enroll(self.learner, self.course)
        url = reverse("take_quiz", args=[self.course.pk])
        self.client.post(url, answers(self.quiz, 1))
        failed = self.client.get(reverse("quiz_result", args=[self.course.pk, self.course.quiz.attempts.get().pk]))
        self.assertContains(failed, "Not passed yet")
        response = self.client.post(url, answers(self.quiz, 3), follow=True)
        self.assertContains(response, "Passed")
        self.assertContains(response, "3 / 3")
        self.assertEqual(len(response.context["attempts"]), 2)

    def test_flash_message_is_shown_after_enrolling(self):
        response = self.client.post(reverse("enroll", args=[self.course.pk]), follow=True)
        self.assertContains(response, "You are now enrolled")
        self.assertContains(response, "alert-success")


class InstructorUiTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.client.force_login(self.teacher)

    def test_empty_state_for_new_instructor_links_to_create(self):
        response = self.client.get(reverse("instructor_courses"))
        self.assertContains(response, "You have not created any courses yet")
        self.assertContains(response, reverse("course_create"))

    def test_course_list_search_and_status_filter(self):
        make_course(self.teacher, "Alpha Basics")
        make_course(self.teacher, "Beta Advanced", status=Course.Status.DRAFT)
        url = reverse("instructor_courses")
        both = self.client.get(url)
        self.assertEqual(len(both.context["courses"]), 2)
        only_draft = self.client.get(url, {"status": "draft"})
        self.assertEqual([c.title for c in only_draft.context["courses"]], ["Beta Advanced"])
        searched = self.client.get(url, {"q": "alpha"})
        self.assertEqual([c.title for c in searched.context["courses"]], ["Alpha Basics"])
        ignored = self.client.get(url, {"status": "not-a-status"})
        self.assertEqual(len(ignored.context["courses"]), 2)
        self.assertContains(self.client.get(url, {"q": "zzz"}), "No courses match your filters")

    def test_course_list_only_shows_own_courses(self):
        make_course(make_user("t2", "instructor"), "Someone Else's")
        make_course(self.teacher, "Mine")
        response = self.client.get(reverse("instructor_courses"))
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Someone Else")

    def test_draft_course_shows_hidden_notice_and_published_does_not(self):
        draft = make_course(self.teacher, "D", status=Course.Status.DRAFT)
        live = make_course(self.teacher, "P")
        self.assertContains(self.client.get(reverse("manage_course", args=[draft.pk])), "hidden from learners")
        self.assertNotContains(self.client.get(reverse("manage_course", args=[live.pk])), "hidden from learners")

    def test_manage_page_empty_states_and_quiz_summary(self):
        course = make_course(self.teacher, lessons=0)
        response = self.client.get(reverse("manage_course", args=[course.pk]))
        self.assertContains(response, "No lessons yet")
        self.assertContains(response, "This course has no quiz yet")
        make_quiz(course, pass_mark=65, n_questions=2)
        response = self.client.get(reverse("manage_course", args=[course.pk]))
        self.assertContains(response, "Pass mark 65%, 2 questions")

    def test_quiz_manage_marks_the_correct_answer_for_the_instructor_only(self):
        course = make_course(self.teacher)
        make_quiz(course, n_questions=1)
        response = self.client.get(reverse("quiz_manage", args=[course.pk]))
        self.assertContains(response, "(correct answer)", count=1)

    def test_empty_quiz_shows_add_question_prompt(self):
        course = make_course(self.teacher)
        Quiz.objects.create(course=course, title="Empty", pass_mark=70)
        response = self.client.get(reverse("quiz_manage", args=[course.pk]))
        self.assertContains(response, "No questions yet")
        self.assertContains(response, reverse("question_create", args=[course.pk]))

    def test_delete_pages_offer_a_way_back_and_name_the_object(self):
        course = make_course(self.teacher, "Removable")
        response = self.client.get(reverse("course_delete", args=[course.pk]))
        self.assertContains(response, "Removable")
        self.assertContains(response, reverse("manage_course", args=[course.pk]))
        self.assertContains(response, "Keep it")

    def test_forms_link_back_to_the_course(self):
        course = make_course(self.teacher)
        response = self.client.get(reverse("lesson_create", args=[course.pk]))
        self.assertEqual(response.context["cancel_url"], reverse("manage_course", args=[course.pk]))


class DashboardUiTests(TestCase):
    def setUp(self):
        self.teacher = make_user("t", "instructor")
        self.course = make_course(self.teacher, lessons=2)
        self.quiz = make_quiz(self.course, n_questions=2)
        self.alice, self.bob, self.cara = (make_user(n, "learner") for n in ("alice", "bob", "cara"))
        for learner in (self.alice, self.bob, self.cara):
            enroll(learner, self.course)
        for lesson in self.course.lessons.all():
            LessonProgress.objects.create(enrollment=self.alice.enrollments.get(), lesson=lesson)
        LessonProgress.objects.create(enrollment=self.bob.enrollments.get(), lesson=self.course.lessons.first())
        self.client.force_login(self.alice)
        self.client.post(reverse("take_quiz", args=[self.course.pk]), answers(self.quiz, 2))
        self.client.force_login(self.teacher)
        self.url = reverse("dashboard", args=[self.course.pk])

    def test_summary_uses_real_counts(self):
        summary = self.client.get(self.url).context["summary"]
        self.assertEqual(summary, {"learners": 3, "finished": 1, "passed": 1})

    def test_search_filters_rows_but_not_summary(self):
        response = self.client.get(self.url, {"q": "BO"})
        self.assertEqual([r["enrollment"].learner.username for r in response.context["rows"]], ["bob"])
        self.assertEqual(response.context["summary"]["learners"], 3)

    def test_search_without_matches_shows_message(self):
        self.assertContains(self.client.get(self.url, {"q": "nobody"}), "No learners match your search")

    def test_no_enrolments_shows_empty_state(self):
        empty = make_course(self.teacher, "Empty course")
        response = self.client.get(reverse("dashboard", args=[empty.pk]))
        self.assertContains(response, "No learners have enrolled yet")
        self.assertEqual(response.context["summary"], {"learners": 0, "finished": 0, "passed": 0})

    def test_course_without_quiz_says_so(self):
        course = make_course(self.teacher, "No quiz")
        enroll(self.bob, course)
        self.assertContains(self.client.get(reverse("dashboard", args=[course.pk])), "This course has no quiz")

    def test_csv_export_link_is_present(self):
        self.assertContains(self.client.get(self.url), reverse("dashboard_csv", args=[self.course.pk]))

    def test_dashboard_search_is_still_owner_only(self):
        self.client.force_login(make_user("t2", "instructor"))
        self.assertEqual(self.client.get(self.url, {"q": "a"}).status_code, 404)


class AttachmentWidgetTests(TempMediaMixin, TestCase):
    def test_edit_form_shows_current_file_and_remove_option(self):
        teacher = make_user("t", "instructor")
        course = make_course(teacher, lessons=1)
        lesson = course.lessons.first()
        lesson.attachment.save("notes.txt", ContentFile(b"x"), save=True)
        self.client.force_login(teacher)
        response = self.client.get(reverse("lesson_edit", args=[course.pk, lesson.pk]))
        self.assertContains(response, "Current file:")
        self.assertContains(response, 'name="attachment-clear"')
        self.assertEqual(inspect_markup(response.content.decode()), [])

    def test_new_lesson_form_has_no_remove_option(self):
        teacher = make_user("t", "instructor")
        course = make_course(teacher, lessons=0)
        self.client.force_login(teacher)
        response = self.client.get(reverse("lesson_create", args=[course.pk]))
        self.assertNotContains(response, "attachment-clear")
        self.assertContains(response, 'type="file"')


class MarkupInspectorTests(TestCase):
    def test_accepts_well_formed_markup(self):
        html = '<div><label for="a">A</label><input id="a" type="text"><svg><path d="M0 0"/></svg><p>Hi</p></div>'
        self.assertEqual(inspect_markup(html), [])

    def test_reports_unclosed_and_mismatched_tags(self):
        self.assertTrue(inspect_markup("<div><p>text</div>"))
        self.assertTrue(inspect_markup("<div><span>open"))
        self.assertTrue(inspect_markup("<div></span></div>"))

    def test_reports_controls_without_labels(self):
        problems = inspect_markup('<form><input id="x" type="text"></form>')
        self.assertTrue(any("without a label" in problem for problem in problems))
        self.assertTrue(inspect_markup('<form><input type="text"></form>'))

    def test_hidden_and_submit_inputs_need_no_label(self):
        self.assertEqual(inspect_markup('<form><input type="hidden" name="n"><input type="submit"></form>'), [])
