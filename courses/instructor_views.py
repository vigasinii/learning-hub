import csv

from django.contrib import messages
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import CourseForm, LessonForm, QuestionForm, QuizForm
from .models import Course, Lesson, Question, Quiz
from .permissions import instructor_required
from .services import progress_percent


def _own_course_or_404(request, pk):
    return get_object_or_404(Course, pk=pk, instructor=request.user)


@instructor_required
def course_list(request):
    own_courses = request.user.courses_taught
    courses = own_courses.annotate(
        lesson_count=Count("lessons", distinct=True),
        enrolment_count=Count("enrollments", distinct=True),
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        courses = courses.filter(title__icontains=query)
    if status in Course.Status.values:
        courses = courses.filter(status=status)
    context = {
        "courses": courses,
        "query": query,
        "status": status,
        "status_choices": Course.Status.choices,
        "has_courses": own_courses.exists(),
    }
    return render(request, "courses/instructor/course_list.html", context)


@instructor_required
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        course = form.save(commit=False)
        course.instructor = request.user
        course.save()
        messages.success(request, "Course created. Now add some lessons.")
        return redirect("manage_course", pk=course.pk)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": "New course", "cancel_url": reverse("instructor_courses")})


@instructor_required
def manage_course(request, pk):
    course = _own_course_or_404(request, pk)
    return render(
        request,
        "courses/instructor/manage_course.html",
        {
            "course": course,
            "lessons": course.lessons.all(),
            "quiz": getattr(course, "quiz", None),
        },
    )


@instructor_required
def course_edit(request, pk):
    course = _own_course_or_404(request, pk)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Course updated.")
        return redirect("manage_course", pk=course.pk)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": f"Edit “{course.title}”", "cancel_url": reverse("manage_course", args=[course.pk])})


@instructor_required
def course_delete(request, pk):
    course = _own_course_or_404(request, pk)
    if request.method == "POST":
        title = course.title
        course.delete()
        messages.success(request, f"Deleted “{title}”.")
        return redirect("instructor_courses")
    return render(request, "courses/instructor/confirm_delete.html", {"object": course, "kind": "course", "cancel_url": reverse("manage_course", args=[course.pk])})


@instructor_required
def lesson_create(request, pk):
    course = _own_course_or_404(request, pk)
    next_order = (course.lessons.aggregate(m=Max("order"))["m"] or 0) + 1
    form = LessonForm(
        request.POST or None,
        request.FILES or None,
        course=course,
        instance=Lesson(course=course),
        initial={"order": next_order},
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Lesson added.")
        return redirect("manage_course", pk=course.pk)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": "New lesson", "multipart": True, "cancel_url": reverse("manage_course", args=[course.pk])})


@instructor_required
def lesson_edit(request, pk, lesson_pk):
    course = _own_course_or_404(request, pk)
    lesson = get_object_or_404(Lesson, pk=lesson_pk, course=course)
    form = LessonForm(request.POST or None, request.FILES or None, course=course, instance=lesson)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Lesson updated.")
        return redirect("manage_course", pk=course.pk)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": "Edit lesson", "multipart": True, "cancel_url": reverse("manage_course", args=[course.pk])})


@instructor_required
def lesson_delete(request, pk, lesson_pk):
    course = _own_course_or_404(request, pk)
    lesson = get_object_or_404(Lesson, pk=lesson_pk, course=course)
    if request.method == "POST":
        lesson.delete()
        messages.success(request, "Lesson deleted.")
        return redirect("manage_course", pk=course.pk)
    return render(request, "courses/instructor/confirm_delete.html", {"object": lesson, "kind": "lesson", "cancel_url": reverse("manage_course", args=[course.pk])})


@instructor_required
def quiz_edit(request, pk):
    course = _own_course_or_404(request, pk)
    quiz = getattr(course, "quiz", None)
    form = QuizForm(request.POST or None, instance=quiz)
    if request.method == "POST" and form.is_valid():
        quiz = form.save(commit=False)
        quiz.course = course
        quiz.save()
        messages.success(request, "Quiz saved.")
        return redirect("quiz_manage", pk=course.pk)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": "Quiz settings", "cancel_url": reverse("manage_course", args=[course.pk])})


@instructor_required
def quiz_manage(request, pk):
    course = _own_course_or_404(request, pk)
    quiz = getattr(course, "quiz", None)
    if quiz is None:
        return redirect("quiz_edit", pk=course.pk)
    questions = quiz.questions.prefetch_related("choices")
    return render(request, "courses/instructor/quiz_manage.html", {"course": course, "quiz": quiz, "questions": questions})


def _own_quiz_or_404(course):
    return get_object_or_404(Quiz, course=course)


@instructor_required
def question_create(request, pk):
    course = _own_course_or_404(request, pk)
    quiz = _own_quiz_or_404(course)
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(quiz)
        messages.success(request, "Question added.")
        return redirect("quiz_manage", pk=course.pk)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": "New question", "cancel_url": reverse("quiz_manage", args=[course.pk])})


@instructor_required
def question_edit(request, pk, question_pk):
    course = _own_course_or_404(request, pk)
    quiz = _own_quiz_or_404(course)
    question = get_object_or_404(Question, pk=question_pk, quiz=quiz)
    if request.method == "POST":
        form = QuestionForm(request.POST)
        if form.is_valid():
            form.save(quiz, question)
            messages.success(request, "Question updated.")
            return redirect("quiz_manage", pk=course.pk)
    else:
        form = QuestionForm.from_question(question)
    return render(request, "courses/instructor/form.html", {"form": form, "heading": "Edit question", "cancel_url": reverse("quiz_manage", args=[course.pk])})


@instructor_required
def question_delete(request, pk, question_pk):
    course = _own_course_or_404(request, pk)
    quiz = _own_quiz_or_404(course)
    question = get_object_or_404(Question, pk=question_pk, quiz=quiz)
    if request.method == "POST":
        question.delete()
        messages.success(request, "Question deleted.")
        return redirect("quiz_manage", pk=course.pk)
    return render(request, "courses/instructor/confirm_delete.html", {"object": question, "kind": "question", "cancel_url": reverse("quiz_manage", args=[course.pk])})


def _dashboard_rows(course):
    total = course.lessons.count()
    enrollments = (
        course.enrollments.select_related("learner")
        .annotate(
            lessons_done=Count("progress", distinct=True),
            best_score=Max("attempts__percent"),
            passes=Count("attempts", filter=Q(attempts__passed=True), distinct=True),
        )
        .order_by("learner__username")
    )
    return total, [
        {
            "enrollment": e,
            "done": e.lessons_done,
            "percent": progress_percent(e.lessons_done, total),
            "best_score": e.best_score,
            "passed": e.passes > 0,
        }
        for e in enrollments
    ]


@instructor_required
def dashboard(request, pk):
    course = _own_course_or_404(request, pk)
    total, rows = _dashboard_rows(course)
    summary = {
        "learners": len(rows),
        "finished": sum(1 for row in rows if total and row["done"] == total),
        "passed": sum(1 for row in rows if row["passed"]),
    }
    query = request.GET.get("q", "").strip()
    if query:
        rows = [row for row in rows if query.lower() in row["enrollment"].learner.username.lower()]
    context = {
        "course": course,
        "total": total,
        "rows": rows,
        "summary": summary,
        "query": query,
        "quiz": getattr(course, "quiz", None),
    }
    return render(request, "courses/instructor/dashboard.html", context)


def _csv_safe(value):
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@instructor_required
def dashboard_csv(request, pk):
    course = _own_course_or_404(request, pk)
    total, rows = _dashboard_rows(course)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="course-{course.pk}-progress.csv"'
    writer = csv.writer(response)
    writer.writerow(["Learner", "Enrolled", "Lessons done", "Total lessons", "Progress %", "Best quiz %", "Passed"])
    for r in rows:
        e = r["enrollment"]
        writer.writerow(
            [
                _csv_safe(e.learner.username),
                e.enrolled_at.date().isoformat(),
                r["done"],
                total,
                r["percent"],
                "" if r["best_score"] is None else r["best_score"],
                "yes" if r["passed"] else "no",
            ]
        )
    return response
