from django import forms
from django.db import transaction

from .models import Choice, Course, Lesson, Question, Quiz

CHOICE_SLOTS = 4
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["title", "description", "status"]


class AttachmentInput(forms.ClearableFileInput):
    template_name = "courses/widgets/attachment_input.html"


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ["title", "content", "video_url", "attachment", "order"]
        widgets = {"attachment": AttachmentInput}

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course

    def clean_attachment(self):
        file = self.cleaned_data.get("attachment")
        if file and hasattr(file, "size") and file.size > MAX_ATTACHMENT_BYTES:
            raise forms.ValidationError("Attachments must be 5 MB or smaller.")
        return file

    def clean_order(self):
        order = self.cleaned_data["order"]
        clash = Lesson.objects.filter(course=self.course, order=order)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"Another lesson in this course already has position {order}.")
        return order


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ["title", "pass_mark"]


class QuestionForm(forms.Form):
    text = forms.CharField(label="Question", max_length=500)
    choice_1 = forms.CharField(max_length=300)
    choice_2 = forms.CharField(max_length=300)
    choice_3 = forms.CharField(max_length=300, required=False)
    choice_4 = forms.CharField(max_length=300, required=False)
    correct = forms.ChoiceField(
        label="Correct answer",
        choices=[(str(i), f"Option {i}") for i in range(1, CHOICE_SLOTS + 1)],
        widget=forms.RadioSelect,
    )

    def clean(self):
        data = super().clean()
        correct = data.get("correct")
        if correct and not data.get(f"choice_{correct}"):
            self.add_error("correct", "The correct answer must be one of the options you filled in.")
        return data

    @classmethod
    def from_question(cls, question, **kwargs):
        initial = {"text": question.text}
        for i, choice in enumerate(question.choices.all(), start=1):
            initial[f"choice_{i}"] = choice.text
            if choice.is_correct:
                initial["correct"] = str(i)
        return cls(initial=initial, **kwargs)

    @transaction.atomic
    def save(self, quiz, question=None):
        data = self.cleaned_data
        if question is None:
            next_order = quiz.questions.count() + 1
            question = Question.objects.create(quiz=quiz, text=data["text"], order=next_order)
        else:
            question.text = data["text"]
            question.save()
            question.choices.all().delete()
        for i in range(1, CHOICE_SLOTS + 1):
            text = data.get(f"choice_{i}")
            if text:
                Choice.objects.create(question=question, text=text, is_correct=str(i) == data["correct"])
        return question
