import uuid
from django.db import models


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=50)
    entity_id = models.UUIDField()
    action = models.CharField(max_length=50)
    actor = models.CharField(max_length=255)
    changes = models.JSONField(default=dict)
    reason = models.TextField(blank=True, help_text="Answers WHY the change occurred")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['entity_type', 'entity_id', '-created_at'],
                name='idx_audit_entity'
            )
        ]

    def __str__(self):
        return f"{self.entity_type}:{self.entity_id} - {self.action} by {self.actor}"

    @classmethod
    def record(cls, entity_type: str, entity_id: uuid.UUID, action: str, actor: str, changes: dict = None, reason: str = ""):
        """Helper classmethod to record an audit log entry within the current transaction."""
        return cls.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            changes=changes or {},
            reason=reason
        )
