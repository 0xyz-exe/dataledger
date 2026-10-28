from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import Optional, List, Any
from datetime import datetime
from app.models.models import UserRole, ImportStatus, JobStatus, DiscrepancyCategory, DiscrepancyStatus


# ── Auth ───────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("display_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Display name cannot be empty")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Workspace ──────────────────────────────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Workspace name cannot be empty")
        return v.strip()


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceMemberResponse(BaseModel):
    id: str
    user_id: str
    workspace_id: str
    role: UserRole
    joined_at: datetime

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.viewer


# ── Dataset ────────────────────────────────────────────────────────────────────

class DatasetCreate(BaseModel):
    name: str
    description: Optional[str] = None


class DatasetResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: Optional[str]
    source_type: str
    original_filename: Optional[str]
    schema_definition: Optional[dict]
    column_mapping: Optional[dict]
    row_count: int
    import_status: ImportStatus
    import_error: Optional[str]
    is_sample: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ColumnMappingRequest(BaseModel):
    mapping: dict[str, str]  # {source_column: canonical_field}


class ImportJobResponse(BaseModel):
    id: str
    dataset_id: str
    status: ImportStatus
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_candidates: int
    error_message: Optional[str]
    validation_report: Optional[dict]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Reconciliation ─────────────────────────────────────────────────────────────

class MatchingRules(BaseModel):
    match_fields: List[str]  # canonical fields to match on
    strategy: str = "exact"  # exact | composite | fuzzy
    amount_tolerance: Optional[str] = None  # decimal string e.g. "0.01"
    date_tolerance_days: int = 0
    case_sensitive: bool = False
    null_handling: str = "exclude"  # exclude | treat_as_empty
    amount_field: Optional[str] = "amount"
    date_field: Optional[str] = "transaction_date"
    fuzzy_threshold: float = 0.85


class ReconciliationJobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    dataset_a_id: str
    dataset_b_id: str
    matching_rules: MatchingRules
    normalization_config: Optional[dict] = None


class ReconciliationJobResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: Optional[str]
    dataset_a_id: str
    dataset_b_id: str
    matching_rules: dict
    normalization_config: Optional[dict]
    status: JobStatus
    engine_version: str
    matched_count: int
    unmatched_count: int
    discrepancy_count: int
    total_processed: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Discrepancy ────────────────────────────────────────────────────────────────

class DiscrepancyResponse(BaseModel):
    id: str
    job_id: str
    category: DiscrepancyCategory
    status: DiscrepancyStatus
    data_a: Optional[dict]
    data_b: Optional[dict]
    diff_fields: Optional[list]
    match_score: Optional[float]
    explanation: Optional[str]
    is_manual_override: bool
    reviewer_notes: Optional[str]
    reviewed_by_id: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class DiscrepancyReviewRequest(BaseModel):
    action: str  # accept | reject | resolve | reopen
    notes: Optional[str] = None

    @field_validator("action")
    @classmethod
    def valid_action(cls, v: str) -> str:
        allowed = {"accept", "reject", "resolve", "reopen"}
        if v not in allowed:
            raise ValueError(f"Action must be one of {allowed}")
        return v


# ── Pagination ─────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int


# ── Audit ──────────────────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: str
    workspace_id: Optional[str]
    actor_id: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    metadata: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}
