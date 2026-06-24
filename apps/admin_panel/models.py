from django.db import models
from apps.users.models import CustomUser


class AdminActionLog(models.Model):
    """
    Immutable audit trail for every admin action.
    Records who did what, to whom, and when.
    """
    ACTION_TYPE_CHOICES = (
        ('approve_employer', 'Approve Employer'),
        ('block_user', 'Block User'),
        ('unblock_user', 'Unblock User'),
        ('flag_user', 'Flag User'),
        ('unflag_user', 'Unflag User'),
        ('flag_job', 'Flag Job'),
        ('unflag_job', 'Unflag Job'),
        ('remove_job', 'Remove Job'),
        ('restore_job', 'Restore Job'),
    )

    TARGET_TYPE_CHOICES = (
        ('user', 'User'),
        ('employer', 'Employer'),
        ('job', 'Job'),
    )

    admin_user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='admin_actions',
        help_text="The admin who performed the action"
    )
    action_type = models.CharField(
        max_length=30,
        choices=ACTION_TYPE_CHOICES,
        help_text="Type of admin action performed"
    )
    target_content_type = models.CharField(
        max_length=20,
        choices=TARGET_TYPE_CHOICES,
        help_text="Type of object the action was performed on"
    )
    target_object_id = models.PositiveIntegerField(
        help_text="Primary key of the target object"
    )
    description = models.TextField(
        blank=True,
        help_text="Human-readable summary of the action"
    )
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        help_text="IP address of the admin at the time of the action"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Admin Action Log'
        verbose_name_plural = 'Admin Action Logs'

    def __str__(self):
        return f"{self.admin_user} — {self.get_action_type_display()} — {self.target_content_type}#{self.target_object_id}"
