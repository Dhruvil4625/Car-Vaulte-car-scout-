from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_user_otp_code_user_otp_expires_user_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="DealRating",
            fields=[
                ("rating_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("score", models.PositiveSmallIntegerField(default=5)),
                ("review", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rated_user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="received_deal_ratings", to="core.user")),
                ("rater", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="given_deal_ratings", to="core.user")),
            ],
        ),
        migrations.AddConstraint(
            model_name="dealrating",
            constraint=models.UniqueConstraint(fields=("rater", "rated_user"), name="unique_deal_rating_pair"),
        ),
    ]