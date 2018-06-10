from django.db import models


class AsyncTest(models.Model):

    myfield = models.CharField(max_length=255)
