SECTIONS = {
    "home": "catalogue",
    "course_detail": "catalogue",
    "my_courses": "my_courses",
    "lesson_detail": "my_courses",
    "take_quiz": "my_courses",
    "quiz_result": "my_courses",
    "instructor_courses": "teach",
    "course_create": "teach",
    "manage_course": "teach",
    "course_edit": "teach",
    "course_delete": "teach",
    "lesson_create": "teach",
    "lesson_edit": "teach",
    "lesson_delete": "teach",
    "quiz_manage": "teach",
    "quiz_edit": "teach",
    "question_create": "teach",
    "question_edit": "teach",
    "question_delete": "teach",
    "dashboard": "teach",
}


def navigation(request):
    match = request.resolver_match
    return {"nav_section": SECTIONS.get(match.url_name, "") if match else ""}
