# NOTES

## Time spent

About 4–5 hours, including reviewing the code and preparing for the interview.

## Tools and AI assistance

I used Claude (Anthropic) as a pair programmer for this project: to read the challenge, propose the architecture, generate the first version of the models, views, templates and tests, and to draft the README and these notes. In a second pass I had it audit the code as a security and QA reviewer and fix what it found (see "Audit fixes" below). The test suite (169 tests at the time of writing) and the HTTP smoke tests were run in an automated environment; I then reviewed the code and prepared to explain and extend it myself. Nothing else (no starter template, no CSS framework, no JavaScript libraries) was used. The only dependency is Django.

## Data model and why

```
User(role) 1--* Course 1--* Lesson
User(learner) 1--* Enrollment *--1 Course
Enrollment 1--* LessonProgress *--1 Lesson
Course 1--0..1 Quiz 1--* Question 1--* Choice
Enrollment 1--* QuizAttempt *--1 Quiz
```

- **One `User` model with a `role` column** (learner or instructor). The spec says each user is one or the other, so a field is the simplest thing that works. Groups or profile tables would add joins for no benefit. Set before the first migration because swapping the user model later is painful.
- **`Enrollment`** is its own table (not a many-to-many field) because it carries data: when you enrolled, and it is the anchor for progress and attempts. A unique constraint stops double enrolment.
- **`LessonProgress`** stores one row per completed lesson. Progress is then a count, which is easy to annotate in a single query for the dashboard. Unique on (enrollment, lesson), so completing twice cannot double count.
- **`Lesson.order`** with a unique constraint on (course, order) gives a deterministic order and prevents two lessons sharing a position. New lessons default to the next free position.
- **`Quiz` is one-to-one with `Course`** (spec: "a quiz at the end"). Pass mark is stored per quiz (default 70).
- **`Choice.is_correct`** has a partial unique constraint, so the database guarantees **at most one** correct choice per question. It cannot guarantee that there is **exactly** one (a question with zero correct choices is still a valid row). "Exactly one" is enforced by the application: the instructor's `QuestionForm` (one "correct" radio that must point at a filled option, minimum two options) and the admin's choice inline validation. Writing `Choice` rows directly from code or the shell bypasses those checks.
- **`QuizAttempt`** keeps every attempt with the score frozen at the time (`correct`, `total`, `percent`, `passed`). Later edits to the quiz do not rewrite history. It links to both the enrollment and the quiz.

## Key decisions and assumptions

- **Permissions are checked in the view**, not just hidden in templates. Learner and instructor pages use decorators (403 for the wrong role). Instructor pages fetch courses with `get_object_or_404(Course, pk=pk, instructor=request.user)`, so another instructor's course is a **404**, which does not reveal that it exists. Draft courses are 404 for learners everywhere (detail, enrol, lessons, quiz).
- **Public sign up is learner-only.** The spec does not say how instructors are created. Letting visitors choose their role would let anyone grant themselves instructor rights, so instructors are created or promoted by an admin in the Django admin (there is a "Promote selected users to instructor" action). The demo instructor comes from `seed_demo`.
- **Quiz marking** counts unanswered or tampered answers as wrong. Pass/fail uses exact integer maths (`correct * 100 >= pass_mark * total`) so rounding cannot make someone pass.
- **Instructors cannot enrol or take quizzes**, and cannot see a course draft as a learner would (they use the management page).
- **Unpublishing a course** hides it from learners again, even those already enrolled; their data is kept.
- **Deleting an instructor account is blocked while they own courses** (`on_delete=PROTECT`), so one admin click cannot wipe a course with every learner's progress.
- **An instructor who owns courses cannot be demoted to learner.** Course pages are instructor-only, so demotion would strand the courses. `User.clean()` blocks it in the admin edit form, and the "Set selected users to learner" bulk action skips such users with a warning naming them while demoting everyone else. Reassign or delete the courses first. (Promoting a learner who has enrolments leaves those enrolments in place but unused, since "My courses" is learner-only.)
- **Attachments are not served from a public `/media/` URL.** A view checks that the user is the owning instructor or an enrolled learner, then streams the file as a download. Uploads are limited to 5 MB and a short list of extensions (this does not prove the contents are safe; files are only ever sent as downloads). Replaced, cleared and deleted attachments are also removed from disk, and a file missing from disk gives a 404, not an error page.
- **Video links** are shown as links, not embedded, to keep things simple and safe.
- **Time zone** is Asia/Kolkata.

## Extras included

Catalogue search (title) and CSV export of learner progress (guarded against spreadsheet formula injection).

## What I left out / would change with more time

- Lesson locking, certificates, Malayalam translation, Docker and deployment (stretch goals not attempted).
- A REST API (not required).
- An invite or approval flow for instructors (today an admin promotes them).
- Login rate limiting, password reset by email, and production settings (HTTPS-only cookies, HSTS, a real database).
- `seed_demo` repairs missing records, but a question that still has *some* choices is left alone (so it can never overwrite instructor edits); only questions with no choices get their choices restored. It never resets the password or role of an existing demo user.
- Instructors cannot delete a quiz (they can edit or delete its questions); a "preview as learner" mode for drafts.
- Reordering lessons by drag and drop (currently an editable position number) and optional shuffling of quiz questions.
- Question `order` is assigned as "count + 1", so deleting a middle question can leave gaps or ties; display order is still stable (ordered by `order, id`).
- Stored quiz attempts do not record which option was picked per question, only the score.
- Accessibility was considered (labels, skip link, focus outlines, keyboard-friendly forms) but not audited with a screen reader.
- No browser-based testing was done; I tested with the Django test client and real HTTP requests against `runserver`.

## Audit fixes (second pass)

- Sign up could be used to become an instructor: now learner-only, with regression tests that tamper with the POST data.
- Deleting an instructor cascaded to courses and all learner data: now `PROTECT`.
- Download of a lesson whose file was missing on disk returned a 500: now 404.
- Replaced or deleted attachments stayed on disk: now removed (after the database commit).
- The admin could save a question with no correct option or only one option: now validated like the instructor form.
- Progress rows and quiz attempts are validated against the enrolment's course (`clean()`); the admin and forms call it.
- `seed_demo` now recreates missing demo records (limited as described under "What I left out": questions that still have some choices are not rewritten) and refuses to adopt an existing account with the wrong role.
- Tests used to write uploads into the real `media/` folder: now a temporary directory.
- A third pass found that the admin could still demote an instructor who owned courses (bulk action and edit form); that is now blocked (see above) and the "exactly one correct answer" claim above was corrected.
- Admin list pages no longer run a query per row (`list_select_related`).

## User interface

- Plain Django templates with one stylesheet (`static/style.css`) built on CSS variables, and a 25 line script (`static/app.js`) for the mobile menu and a busy state on submit buttons. No frontend framework or extra dependency. Icons are inline SVG from a single template (`templates/components/icon.html`).
- Reusable template components live in `templates/components/`: icons, form fields, course card, progress bar, status badge, empty state and form errors. Every form is rendered through the same field component so labels, help text and errors look and behave the same.
- Only real data is shown: lesson counts, progress, scores and the dashboard summary (enrolled, finished all lessons, passed the quiz) are computed from the database. There are no ratings, student counts or other invented figures.
- Small view additions support the UI (enrolled state in the catalogue, next lesson, progress in the lesson sidebar, attempt count on the quiz page, search and status filter for instructors, learner search on the dashboard). Permission checks, scoring and progress logic were not changed.
- Accessibility: semantic landmarks, a skip link, a label for every control (checked by tests), visible focus styles, status messages announced to screen readers, reduced motion respected. Text and control-border contrast was computed against WCAG AA while designing the palette.
- Not verified: the pages were not viewed in a real browser. Markup validity, labels, rendering of every page for each role and HTTP responses are covered by tests, but visual layout, mobile widths and horizontal overflow still need a manual look. Lessons are reordered by editing the position number, there is no drag and drop.
- Source code contains no explanatory comments (only the `manage.py` shebang) and a few docstrings that state non-obvious rules; the reasoning for design choices is in this file.
