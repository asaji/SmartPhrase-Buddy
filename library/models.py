from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone

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

class CaseDraft(models.Model):
    """One opt-in, resumable working copy of an operative/procedure case draft.

    Deliberate, scoped exception to the "no case text persisted" boundary: it
    exists so a case started on one machine can be finished on another. Only the
    current working narrative is kept — never AI output, free-text instructions,
    the session draft-history checkpoints, or the Epic header. Owner-scoped, one
    row per master template (an explicit save overwrites it), auto-expired after
    CASE_DRAFT_TTL, and excluded from the portable JSON export/backup.
    """
    TTL = timedelta(days=7)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    template = models.ForeignKey(Template,on_delete=models.CASCADE,related_name='case_drafts')
    kind = models.CharField(max_length=20)
    base_version = models.PositiveIntegerField()
    label = models.CharField(max_length=200,blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['owner','template'],name='one_case_draft_per_template')]
        indexes = [models.Index(fields=['owner','updated_at'])]

    @classmethod
    def prune(cls,owner):
        """Delete this owner's drafts past their TTL. Cheap; called before every list/read/save."""
        cls.objects.filter(owner=owner,updated_at__lt=timezone.now()-cls.TTL).delete()

    @property
    def stale_base(self):
        return self.template.version != self.base_version


class PendingImport(models.Model):
    """A phrase extracted from an uploaded PDF, waiting to be reviewed and imported.

    Reusable-template import material, not a case draft: it is persisted so the
    PDF is uploaded once and the user sifts the list over multiple sessions.
    Rows leave the queue when a template is approved from them (imported_at set)
    or the user skips them (dismissed). Not included in template export/backup.
    """
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    batch = models.CharField(max_length=32)
    source_name = models.CharField(max_length=200,blank=True)
    name = models.CharField(max_length=200,blank=True)
    text = models.TextField()
    html = models.TextField(blank=True)
    flags = models.JSONField(default=list)
    order = models.PositiveIntegerField(default=0)
    text_hash = models.CharField(max_length=64)
    imported_at = models.DateTimeField(null=True,blank=True)
    imported_template = models.ForeignKey(Template,null=True,blank=True,on_delete=models.SET_NULL)
    dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['batch','order']
        indexes = [models.Index(fields=['owner','dismissed','imported_at'])]
