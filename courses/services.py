def progress_percent(done, total):
    if not total:
        return 0
    return round(done * 100 / total)


def score_quiz(correct, total, pass_mark):
    """Return (rounded_percent, passed). Passing uses exact integer maths, never the rounded percent."""
    if total == 0:
        return 0, False
    percent = round(correct * 100 / total)
    passed = correct * 100 >= pass_mark * total
    return percent, passed


def grade_answers(quiz, selected):
    """Return (correct, total). `selected` maps question id to choice id; anything else counts as wrong."""
    questions = quiz.questions.prefetch_related("choices")
    correct = total = 0
    for question in questions:
        total += 1
        right_ids = {c.id for c in question.choices.all() if c.is_correct}
        if selected.get(question.id) in right_ids:
            correct += 1
    return correct, total
