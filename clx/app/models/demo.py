import uuid

from django.conf import settings
from django.core.files.storage import Storage, storages
from django.db import models
from django.utils import timezone

from clx.app.models.base import BaseModel


def demo_upload_storage() -> Storage:
    return storages["private"]


def demo_upload_path(instance: "DemoUpload", filename: str) -> str:
    return f"{instance.user_id}/{instance.id}/{filename}"


class DemoJob(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="demo_jobs",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    fail_rate = models.FloatField(default=0)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class DemoUpload(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="demo_uploads",
    )
    file = models.FileField(
        storage=demo_upload_storage,
        upload_to=demo_upload_path,
        max_length=500,
    )
    name = models.CharField(max_length=255)
    size = models.BigIntegerField()
    content_type = models.CharField(max_length=200, blank=True)


class DemoDocket(BaseModel):
    docket_id = models.CharField(max_length=50, unique=True)
    court_id = models.CharField(max_length=20)
    pacer_case_id = models.CharField(max_length=50, blank=True)
    case_name = models.CharField(max_length=500)
    docket_number = models.CharField(max_length=100)
    date_filed = models.DateField()
    date_terminated = models.DateField(null=True, blank=True)
    date_converted = models.DateField(null=True, blank=True)
    date_discharged = models.DateField(null=True, blank=True)
    assigned_to_str = models.CharField(max_length=200, blank=True)
    referred_to_str = models.CharField(max_length=500, blank=True)
    cause = models.CharField(max_length=500, blank=True)
    nature_of_suit = models.CharField(max_length=200, blank=True)
    jury_demand = models.CharField(max_length=50, blank=True)
    jurisdiction = models.CharField(max_length=100, blank=True)
    demand = models.CharField(max_length=100, blank=True)
    mdl_status = models.CharField(max_length=200, blank=True)
    ordered_by = models.CharField(max_length=50, blank=True)
    federal_defendant_number = models.CharField(max_length=50, blank=True)
    federal_dn_case_type = models.CharField(max_length=20, blank=True)
    federal_dn_office_code = models.CharField(max_length=20, blank=True)
    federal_dn_judge_initials_assigned = models.CharField(
        max_length=20, blank=True
    )
    federal_dn_judge_initials_referred = models.CharField(
        max_length=20, blank=True
    )


class DemoDocketEntry(BaseModel):
    docket = models.ForeignKey(
        DemoDocket,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    date_filed = models.DateField()
    date_entered = models.DateField(null=True, blank=True)
    document_number = models.CharField(max_length=20, blank=True)
    pacer_doc_id = models.CharField(max_length=50, blank=True)
    pacer_seq_no = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)


class DemoParty(BaseModel):
    docket = models.ForeignKey(
        DemoDocket,
        on_delete=models.CASCADE,
        related_name="parties",
    )
    name = models.CharField(max_length=500)
    type = models.CharField(max_length=100)
    extra_info = models.TextField(blank=True)
    date_terminated = models.DateField(null=True, blank=True)


class DemoAttorney(BaseModel):
    party = models.ForeignKey(
        DemoParty,
        on_delete=models.CASCADE,
        related_name="attorneys",
    )
    name = models.CharField(max_length=200)
    contact = models.TextField(blank=True)
    roles = models.JSONField(default=list, blank=True)


class DemoChatThread(BaseModel):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="demo_chat_threads",
    )
    agent = models.CharField(max_length=50)
    title = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IDLE,
    )
    turn = models.UUIDField(default=uuid.uuid4, editable=False)
    touched_at = models.DateTimeField(default=timezone.now, editable=False)
    state = models.JSONField(default=dict, blank=True)


class DemoChatMessage(BaseModel):
    class Kind(models.TextChoices):
        CHAT = "chat", "Chat"
        META = "meta", "Meta"
        COMPACTION = "compaction", "Compaction"

    thread = models.ForeignKey(
        DemoChatThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.CHAT,
    )
    data = models.JSONField(default=dict, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost = models.FloatField(default=0.0)
