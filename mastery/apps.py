from django.apps import AppConfig


class MasteryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mastery"

    def ready(self):
        import mastery.signals  # noqa: F401