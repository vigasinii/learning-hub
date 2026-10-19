from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from courses.models import Choice, QuizAttempt
from courses.services import grade_answers, progress_percent, score_quiz

from .helpers import answers, enroll, make_course, make_quiz, make_user


class ScoreMathTests(SimpleTestCase):
    def test_exact_pass_mark_passes(self):
        self.assertEqual(score_quiz(7, 10, 70), (70, True))

    def test_just_below_pass_mark_fails(self):
        self.assertEqual(score_quiz(6, 10, 70), (60, False))

    def test_rounding_never_causes_a_pass(self):
        percent, passed = score_quiz(2, 3, 67)
        self.assertEqual(percent, 67)
        self.assertFalse(passed)

    def test_perfect_and_zero(self):
        self.assertEqual(score_quiz(3, 3, 100), (100, True))
        self.assertEqual(score_quiz(0, 3, 70), (0, False))

    def test_empty_quiz_never_passes(self):
        self.assertEqual(score_quiz(0, 0, 70), (0, False))

    def test_progress_percent_matches_spec_example(self):
        self.assertEqual(progress_percent(4, 7), 57)
        self.assertEqual(progress_percent(0, 0), 0)


class GradeAnswersTests(TestCase):
    def setUp(self):
        self.course = make_course(make_user("t", "instructor"))
        self.quiz = make_quiz(self.course, n_questions=3)

    def test_all_correct(self):
        self.assertEqual(grade_answers(self.quiz, {k_id(k): v for k, v in answers(self.quiz, 3).items()}), (3, 3))

    def test_partial(self):
        self.assertEqual(grade_answers(self.quiz, {k_id(k): v for k, v in answers(self.quiz, 2).items()}), (2, 3))

    def test_unanswered_counts_wrong(self):
        self.assertEqual(grade_answers(self.quiz, {}), (0, 3))

    def test_choice_from_another_question_does_not_score(self):
        q1, q2, _ = list(self.quiz.questions.all())
        other_correct = Choice.objects.get(question=q2, is_correct=True)
        self.assertEqual(grade_answers(self.quiz, {q1.id: other_correct.id}), (0, 3))


def k_id(key):
    return int(key.split("_")[1])


class TakeQuizViewTests(TestCase):
    def setUp(self):
        self.instructor = make_user("t", "instructor")
        self.learner = make_user("l", "learner")
        self.course = make_course(self.instructor)
        self.quiz = make_quiz(self.course, pass_mark=70, n_questions=3)
        enroll(self.learner, self.course)
        self.client.force_login(self.learner)
        self.url = reverse("take_quiz", args=[self.course.pk])

    def test_passing_attempt_is_saved_and_shown(self):
        response = self.client.post(self.url, answers(self.quiz, 3), follow=True)
        attempt = QuizAttempt.objects.get()
        self.assertEqual((attempt.correct, attempt.total, attempt.percent, attempt.passed), (3, 3, 100, True))
        self.assertContains(response, "3 / 3")
        self.assertContains(response, "Passed")

    def test_failing_attempt(self):
        self.client.post(self.url, answers(self.quiz, 1))
        attempt = QuizAttempt.objects.get()
        self.assertEqual((attempt.correct, attempt.percent, attempt.passed), (1, 33, False))

    def test_every_attempt_is_kept(self):
        self.client.post(self.url, answers(self.quiz, 1))
        self.client.post(self.url, answers(self.quiz, 3))
        self.assertEqual(QuizAttempt.objects.count(), 2)

    def test_garbage_input_is_marked_wrong_not_a_crash(self):
        response = self.client.post(self.url, {f"question_{q.id}": "abc" for q in self.quiz.questions.all()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(QuizAttempt.objects.get().correct, 0)

    def test_cannot_view_someone_elses_result(self):
        self.client.post(self.url, answers(self.quiz, 3))
        attempt = QuizAttempt.objects.get()
        other = make_user("l2", "learner")
        enroll(other, self.course)
        self.client.force_login(other)
        response = self.client.get(reverse("quiz_result", args=[self.course.pk, attempt.pk]))
        self.assertEqual(response.status_code, 404)
