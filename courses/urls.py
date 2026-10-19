from django.urls import path

from . import instructor_views as iv
from . import learner_views as lv

urlpatterns = [
    path("", lv.catalogue, name="home"),
    path("courses/<int:pk>/", lv.course_detail, name="course_detail"),
    path("courses/<int:pk>/enroll/", lv.enroll, name="enroll"),
    path("my-courses/", lv.my_courses, name="my_courses"),
    path("lessons/<int:pk>/", lv.lesson_detail, name="lesson_detail"),
    path("lessons/<int:pk>/complete/", lv.complete_lesson, name="complete_lesson"),
    path("lessons/<int:pk>/attachment/", lv.lesson_attachment, name="lesson_attachment"),
    path("courses/<int:pk>/quiz/", lv.take_quiz, name="take_quiz"),
    path("courses/<int:pk>/quiz/result/<int:attempt_pk>/", lv.quiz_result, name="quiz_result"),
    path("teach/", iv.course_list, name="instructor_courses"),
    path("teach/courses/new/", iv.course_create, name="course_create"),
    path("teach/courses/<int:pk>/", iv.manage_course, name="manage_course"),
    path("teach/courses/<int:pk>/edit/", iv.course_edit, name="course_edit"),
    path("teach/courses/<int:pk>/delete/", iv.course_delete, name="course_delete"),
    path("teach/courses/<int:pk>/lessons/new/", iv.lesson_create, name="lesson_create"),
    path("teach/courses/<int:pk>/lessons/<int:lesson_pk>/edit/", iv.lesson_edit, name="lesson_edit"),
    path("teach/courses/<int:pk>/lessons/<int:lesson_pk>/delete/", iv.lesson_delete, name="lesson_delete"),
    path("teach/courses/<int:pk>/quiz/", iv.quiz_manage, name="quiz_manage"),
    path("teach/courses/<int:pk>/quiz/settings/", iv.quiz_edit, name="quiz_edit"),
    path("teach/courses/<int:pk>/quiz/questions/new/", iv.question_create, name="question_create"),
    path("teach/courses/<int:pk>/quiz/questions/<int:question_pk>/edit/", iv.question_edit, name="question_edit"),
    path("teach/courses/<int:pk>/quiz/questions/<int:question_pk>/delete/", iv.question_delete, name="question_delete"),
    path("teach/courses/<int:pk>/dashboard/", iv.dashboard, name="dashboard"),
    path("teach/courses/<int:pk>/dashboard.csv", iv.dashboard_csv, name="dashboard_csv"),
]
