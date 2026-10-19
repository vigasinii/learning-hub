from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Course, Enrollment, Lesson, LessonProgress, QuizAttempt
from .permissions import learner_required
from .services import grade_answers, progress_percent, score_quiz


def _published_course_or_404(pk):
    return get_object_or_404(Course, pk=pk, status=Course.Status.PUBLISHED)


def _enrollment_or_none(user, course):
    if not user.is_authenticated:
        return None
    return Enrollment.objects.filter(learner=user, course=course).first()


@login_required
def catalogue(request):
    courses = (
        Course.objects.filter(status=Course.Status.PUBLISHED)
        .select_related("instructor")
        .annotate(lesson_count=Count("lessons"))
    )
    query = request.GET.get("q", "").strip()
    if query:
        courses = courses.filter(title__icontains=query)
    enrolled_ids = set()
    if request.user.is_learner:
        enrolled_ids = set(Enrollment.objects.filter(learner=request.user).values_list("course_id", flat=True))
    return render(
        request,
        "courses/catalogue.html",
        {"courses": courses, "query": query, "enrolled_ids": enrolled_ids},
    )


@login_required
def course_detail(request, pk):
    course = _published_course_or_404(pk)
    enrollment = _enrollment_or_none(request.user, course)
    lessons = list(course.lessons.all())
    done_ids = set()
    if enrollment:
        done_ids = set(enrollment.progress.values_list("lesson_id", flat=True))
    next_lesson = next((lesson for lesson in lessons if lesson.pk not in done_ids), None)
    return render(
        request,
        "courses/course_detail.html",
        {
            "course": course,
            "lessons": lessons,
            "enrollment": enrollment,
            "done_ids": done_ids,
            "done_count": len(done_ids),
            "total_lessons": len(lessons),
            "percent": progress_percent(len(done_ids), len(lessons)),
            "next_lesson": next_lesson if enrollment else None,
            "quiz": getattr(course, "quiz", None),
        },
    )


@learner_required
@require_POST
def enroll(request, pk):
    course = _published_course_or_404(pk)
    _, created = Enrollment.objects.get_or_create(learner=request.user, course=course)
    if created:
        messages.success(request, f"You are now enrolled in “{course.title}”.")
    else:
        messages.info(request, "You are already enrolled in this course.")
    return redirect("course_detail", pk=course.pk)


@learner_required
def my_courses(request):
    enrollments = (
        Enrollment.objects.filter(learner=request.user, course__status=Course.Status.PUBLISHED)
        .select_related("course")
        .annotate(
            total_lessons=Count("course__lessons", distinct=True),
            done_lessons=Count("progress", distinct=True),
        )
    )
    rows = [(e, progress_percent(e.done_lessons, e.total_lessons)) for e in enrollments]
    return render(request, "courses/my_courses.html", {"rows": rows})


def _enrolled_lesson_or_redirect(request, lesson):
    course = lesson.course
    if not course.is_published:
        raise Http404
    enrollment = _enrollment_or_none(request.user, course)
    if enrollment is None:
        messages.error(request, "Please enrol in this course to view its lessons.")
        return None, redirect("course_detail", pk=course.pk)
    return enrollment, None


@learner_required
def lesson_detail(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("course"), pk=pk)
    enrollment, denied = _enrolled_lesson_or_redirect(request, lesson)
    if denied:
        return denied
    lessons = list(lesson.course.lessons.all())
    index = lessons.index(lesson)
    done_ids = set(enrollment.progress.values_list("lesson_id", flat=True))
    return render(
        request,
        "courses/lesson_detail.html",
        {
            "lesson": lesson,
            "course": lesson.course,
            "lessons": lessons,
            "done_ids": done_ids,
            "done_count": len(done_ids),
            "total_lessons": len(lessons),
            "percent": progress_percent(len(done_ids), len(lessons)),
            "previous_lesson": lessons[index - 1] if index > 0 else None,
            "next_lesson": lessons[index + 1] if index < len(lessons) - 1 else None,
            "is_done": lesson.pk in done_ids,
            "quiz": getattr(lesson.course, "quiz", None),
        },
    )


@learner_required
@require_POST
def complete_lesson(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("course"), pk=pk)
    enrollment, denied = _enrolled_lesson_or_redirect(request, lesson)
    if denied:
        return denied
    LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
    messages.success(request, f"Marked “{lesson.title}” as complete.")
    return redirect("lesson_detail", pk=lesson.pk)


@login_required
def lesson_attachment(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("course"), pk=pk)
    if not lesson.attachment:
        raise Http404
    course = lesson.course
    is_owner = request.user.is_instructor and course.instructor_id == request.user.id
    is_enrolled = (
        request.user.is_learner
        and course.is_published
        and Enrollment.objects.filter(learner=request.user, course=course).exists()
    )
    if not (is_owner or is_enrolled):
        raise Http404
    try:
        handle = lesson.attachment.open("rb")
    except FileNotFoundError:
        raise Http404
    return FileResponse(handle, as_attachment=True)


def _selected_answers(request, quiz):
    selected = {}
    for question in quiz.questions.all():
        raw = request.POST.get(f"question_{question.id}", "")
        if raw.isdigit():
            selected[question.id] = int(raw)
    return selected


@learner_required
def take_quiz(request, pk):
    course = _published_course_or_404(pk)
    enrollment = _enrollment_or_none(request.user, course)
    if enrollment is None:
        messages.error(request, "Please enrol in this course before taking its quiz.")
        return redirect("course_detail", pk=course.pk)
    quiz = getattr(course, "quiz", None)
    if quiz is None or not quiz.questions.exists():
        messages.info(request, "This course does not have a quiz yet.")
        return redirect("course_detail", pk=course.pk)

    if request.method == "POST":
        correct, total = grade_answers(quiz, _selected_answers(request, quiz))
        percent, passed = score_quiz(correct, total, quiz.pass_mark)
        attempt = QuizAttempt.objects.create(
            enrollment=enrollment, quiz=quiz, correct=correct, total=total, percent=percent, passed=passed
        )
        return redirect("quiz_result", pk=course.pk, attempt_pk=attempt.pk)

    questions = quiz.questions.prefetch_related("choices")
    return render(
        request,
        "courses/quiz_take.html",
        {
            "course": course,
            "quiz": quiz,
            "questions": questions,
            "attempt_count": QuizAttempt.objects.filter(enrollment=enrollment).count(),
        },
    )


@learner_required
def quiz_result(request, pk, attempt_pk):
    course = _published_course_or_404(pk)
    attempt = get_object_or_404(
        QuizAttempt.objects.select_related("quiz"),
        pk=attempt_pk,
        enrollment__learner=request.user,
        enrollment__course=course,
    )
    attempts = QuizAttempt.objects.filter(enrollment=attempt.enrollment)
    return render(
        request,
        "courses/quiz_result.html",
        {"course": course, "attempt": attempt, "attempts": attempts},
    )
