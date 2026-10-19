# Learning Hub

A small learning management system built with Django for the PUCAR coding challenge. Instructors write and publish courses (lessons plus a multiple choice quiz) and see how learners are doing. Learners browse published courses, enrol, complete lessons and take quizzes.

Stack: Python 3.12, Django 5.2 (LTS), SQLite, server-rendered Django templates. No other dependencies.

## Quick start

Requires Python 3.10 or newer.

```bash
git clone <repo-url> pucar_lms
cd pucar_lms

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate             # creates db.sqlite3
python manage.py seed_demo           # demo users, a published course, a quiz
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with a demo account below.

## Demo accounts

All demo accounts use the password `demo-pass-123`.

| Username      | Role       | Notes                                         |
|---------------|------------|-----------------------------------------------|
| `instructor1` | Instructor | Owns "E-filing for Court Clerks" (published) and a draft course |
| `learner1`    | Learner    | Enrolled, 2 of 4 lessons done                 |
| `learner2`    | Learner    | Enrolled, nothing done yet                    |

`seed_demo` is safe to run repeatedly: it only creates what is missing (users, courses, lessons, quiz, questions, enrolments, progress, and the choices of a question that has none), never deletes anything and never changes an existing account's password or role. It does not rewrite a question that still has some choices, because that could overwrite an instructor's edits; to restore such a question, delete it in the admin and rerun the command. If a user named `instructor1`, `learner1` or `learner2` already exists with a different role, it stops with an error instead of touching that account.

### Instructors and the admin

Public sign up **always creates a learner**. Instructors are created or promoted by an administrator:

```bash
python manage.py createsuperuser        # then open http://127.0.0.1:8000/admin/
```

In the admin: **Users**, tick the users, choose the action "Promote selected users to instructor" (or edit a user and change the *Role* field). An instructor who still owns courses cannot be demoted to learner; reassign or delete their courses first. Admin accounts you create with `createsuperuser` have the learner role in the LMS itself; use the admin for management.

## Running the tests

```bash
python manage.py test
```

The suite (169 tests, a few seconds) covers sign up and login rules, quiz marking including exact pass-mark boundaries, every permission rule in R7, cross-user and cross-instructor access, progress, the instructor dashboard and CSV, forms, upload validation and download protection, attachment file clean-up, admin access, database integrity, repeatable demo seeding, and the user interface (every page renders with well-formed markup and labelled form controls, navigation state, empty states, and that quiz answers are never shown before submitting). Tests use a temporary directory for uploads, so they never touch your `media/` folder.

## Try it out (suggested walkthrough)

1. Log in as `learner1`: catalogue, "My courses" (2 of 4 lessons, 50%), open a lesson and mark it complete, take the quiz, see your score.
2. Try `/courses/2/` (the draft course) as a learner: it returns 404.
3. Log in as `instructor1`: "Teach" lists your courses; open the course to add or edit lessons, edit the quiz and questions, and open the **Learner dashboard** (or export it as CSV).
4. Sign up a new account via the Sign up page (it becomes a learner). To make it an instructor, promote it in the admin as described above.

## Features

| Requirement | Where |
|-------------|-------|
| R1 Accounts and roles | `accounts/` (custom `User` with a `role` field; sign up, log in, log out) |
| R2 Courses and lessons | `courses/instructor_views.py`; ordered lessons with optional video link and attachment |
| R3 Catalogue and enrolment | `courses/learner_views.py` (`catalogue`, `course_detail`, `enroll`, `my_courses`) |
| R4 Progress | `LessonProgress` model; "4 of 7 lessons done (57%)" |
| R5 Quizzes | `Quiz`, `Question`, `Choice`, `QuizAttempt`; pass mark per quiz (default 70%); every attempt is saved |
| R6 Instructor dashboard | `/teach/courses/<id>/dashboard/` |
| R7 Permissions | `courses/permissions.py` decorators plus ownership checks in each view; see tests |
| R8 Django admin | `accounts/admin.py`, `courses/admin.py` (list columns, filters, inlines) |
| R9 Tests | `courses/tests/` |

Extras beyond the core: catalogue search, CSV export of learner progress, permission-checked file downloads, admin action to promote instructors.

## Configuration

Development works with no configuration. For anything else, use environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DJANGO_DEBUG` | `1` | Set to `0` for production |
| `DJANGO_SECRET_KEY` | dev-only key | **Required** when `DJANGO_DEBUG=0` |
| `DJANGO_ALLOWED_HOSTS` | empty | Comma separated host names |

When `DJANGO_DEBUG=0`, session and CSRF cookies are marked HTTPS-only. HTTPS redirects and HSTS are left to the web server or proxy.

## Project layout

```
config/                 project settings and root URLs
accounts/               custom User model, sign up form and view, admin
courses/
  models.py             Course, Lesson, Enrollment, LessonProgress, Quiz, Question, Choice, QuizAttempt
  services.py           quiz grading and progress maths (pure functions)
  permissions.py        role_required / instructor_required / learner_required
  forms.py              Course, Lesson, Quiz and Question forms
  learner_views.py      catalogue, enrolment, lessons, quiz taking
  instructor_views.py   course/lesson/quiz management, dashboard, CSV
  context_processors.py navigation state for the header
  management/commands/seed_demo.py
  templates/            widget template for the attachment field
  tests/
templates/              base layout, pages, and components/ (icons, field, course card, progress, badges)
static/                 style.css (design tokens and components) and app.js (mobile menu, submit state)
```

## Known limitations

- SQLite and local file storage only; no deployment configuration is included.
- No login rate limiting, password reset or email verification.
- Instructors cannot delete a quiz (only its questions) or preview a draft as a learner.
- Quiz attempts store the score, not which option was chosen for each question.
- Attachment checks are by extension and size only; that does not prove a file's contents are safe. Files are always sent as downloads, never rendered inline.
- Lesson locking, certificates, translations, Docker and a REST API were not built.
- Tested with the Django test client and HTTP requests against `runserver`; the layout has not been viewed in a real browser, so check it on a phone-sized window yourself.

See `NOTES.md` for design decisions and assumptions.
