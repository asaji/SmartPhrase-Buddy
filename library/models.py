from django.db import models
from django.conf import settings

class Template(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    epic_name = models.CharField(max_length=200,blank=True)
    kind = models.CharField(max_length=20,default='clinic')
    tags = models.JSONField(default=list)
    aliases = models.JSONField(default=list)
    favorite = models.BooleanField(default=False)
    header = models.TextField(blank=True)
    content = models.TextField()
    original_source = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Revision(models.Model):
    template = models.ForeignKey(Template,on_delete=models.CASCADE,related_name='revisions')
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['template','version'],name='unique_revision')]
