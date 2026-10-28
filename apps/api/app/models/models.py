"""SQLAlchemy ORM models."""
import uuid
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import (
    String, Text, Boolean, DateTime, Integer, Numeric, ForeignKey,
    Enum as SAEnum, JSON, BigInteger, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ──────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    analyst = "analyst"
    viewer = "viewer"


class ImportStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JobStatus(str, enum.Enum):
    draft = "draft"
    queued = "queued"
    running = "running"
    completed = "completed"
    completed_with_warnings = "completed_with_warnings"
    failed = "failed"
    cancelled = "cancelled"


class DiscrepancyCategory(str, enum.Enum):
    matched = "matched"
    missing_in_a = "missing_in_a"
    missing_in_b = "missing_in_b"
    amount_mismatch = "amount_mismatch"
    date_mismatch = "date_mismatch"
    reference_mismatch = "reference_mismatch"
    currency_mismatch = "currency_mismatch"
    duplicate_candidate = "duplicate_candidate"
    ambiguous_match = "ambiguous_match"
    invalid_record = "invalid_record"


class DiscrepancyStatus(str, enum.Enum):
    open = "open"
    reviewed = "reviewed"
    resolved = "resolved"
    reopened = "reopened"


# ── Models ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    workspace_memberships: Mapped[List["WorkspaceMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="actor")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    members: Mapped[List["WorkspaceMember"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    datasets: Mapped[List["Dataset"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    reconciliation_jobs: Mapped[List["ReconciliationJob"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="workspace")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.viewer, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="workspace_memberships")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="file")
    original_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    internal_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    schema_definition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    column_mapping: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    import_status: Mapped[ImportStatus] = mapped_column(SAEnum(ImportStatus), default=ImportStatus.pending)
    import_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    workspace: Mapped["Workspace"] = relationship(back_populates="datasets")
    rows: Mapped[List["DatasetRow"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    import_jobs: Mapped[List["ImportJob"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class DatasetRow(Base):
    __tablename__ = "dataset_rows"
    __table_args__ = (Index("ix_dataset_rows_dataset_id", "dataset_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    canonical_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    validation_errors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    dataset: Mapped["Dataset"] = relationship(back_populates="rows")


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(SAEnum(ImportStatus), default=ImportStatus.pending)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_candidates: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset: Mapped["Dataset"] = relationship(back_populates="import_jobs")


class ReconciliationJob(Base):
    __tablename__ = "reconciliation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dataset_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False)
    dataset_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False)
    matching_rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    normalization_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), default=JobStatus.draft)
    engine_version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, default=0)
    total_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    workspace: Mapped["Workspace"] = relationship(back_populates="reconciliation_jobs")
    dataset_a: Mapped["Dataset"] = relationship(foreign_keys=[dataset_a_id])
    dataset_b: Mapped["Dataset"] = relationship(foreign_keys=[dataset_b_id])
    discrepancies: Mapped[List["Discrepancy"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Discrepancy(Base):
    __tablename__ = "discrepancies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("reconciliation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[DiscrepancyCategory] = mapped_column(SAEnum(DiscrepancyCategory), nullable=False)
    status: Mapped[DiscrepancyStatus] = mapped_column(SAEnum(DiscrepancyStatus), default=DiscrepancyStatus.open)
    row_a_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("dataset_rows.id", ondelete="SET NULL"), nullable=True)
    row_b_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("dataset_rows.id", ondelete="SET NULL"), nullable=True)
    data_a: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    data_b: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    diff_fields: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    match_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job: Mapped["ReconciliationJob"] = relationship(back_populates="discrepancies")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_workspace_id", "workspace_id"), Index("ix_audit_logs_created_at", "created_at"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workspace: Mapped[Optional["Workspace"]] = relationship(back_populates="audit_logs")
    actor: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")
