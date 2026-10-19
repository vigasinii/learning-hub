import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('courses', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='instructor',
            field=models.ForeignKey(limit_choices_to={'role': 'instructor'}, on_delete=django.db.models.deletion.PROTECT, related_name='courses_taught', to=settings.AUTH_USER_MODEL),
        ),
    ]
