from django.contrib.auth.forms import UserCreationForm

from .models import User


class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.LEARNER
        if commit:
            user.save()
        return user
