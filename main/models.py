from django.db import models

class MESSAGE(models.Model):
    text = models.TextField(blank=True, null=True)
    images = models.JSONField(blank=True, null=True)  # Для хранения списка URL изображений
    sent = models.BooleanField(default=False)
    def __str__(self):
        return self.text