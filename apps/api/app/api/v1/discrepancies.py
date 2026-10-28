"""Discrepancy review endpoints."""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import get_workspace_member, require_role
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.models.models import Discrepancy, ReconciliationJob, WorkspaceMember, UserRole, DiscrepancyStatus, DiscrepancyCategory
from app.schemas.schemas import DiscrepancyResponse, DiscrepancyReviewRequest
from app.services.audit import log_event

router = APIRouter(tags=["discrepancies"])


async def _get_discrepancy_checked(discrepancy_id: str, workspace_id: str, db: AsyncSession) -> Discrepancy:
    result = await db.execute(select(Discrepancy).where(Discrepancy.id == discrepancy_id))
    d = result.scalar_one_or_none()
    if not d:
        raise NotFoundError("Discrepancy")
    # Verify workspace isolation
    job_result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == d.job_id))
    job = job_result.scalar_one_or_none()
    if not job or job.workspace_id != workspace_id:
        raise ForbiddenError("Discrepancy not in this workspace")
    return d


@router.get("/workspaces/{workspace_id}/discrepancies", response_model=dict)
async def list_discrepancies(
    workspace_id: str,
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    # Subquery: jobs in this workspace
    workspace_job_ids = select(ReconciliationJob.id).where(ReconciliationJob.workspace_id == workspace_id)
    q = select(Discrepancy).where(Discrepancy.job_id.in_(workspace_job_ids))

    if job_id:
        q = q.where(Discrepancy.job_id == job_id)
    if category:
        try:
            q = q.where(Discrepancy.category == DiscrepancyCategory(category))
        except ValueError:
            raise ValidationError(f"Invalid category: {category}")
    if status:
        try:
            q = q.where(Discrepancy.status == DiscrepancyStatus(status))
        except ValueError:
            raise ValidationError(f"Invalid status: {status}")

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar()
    items_result = await db.execute(q.order_by(Discrepancy.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    items = items_result.scalars().all()

    return {
        "items": [
            {
                "id": d.id,
                "job_id": d.job_id,
                "category": d.category,
                "status": d.status,
                "data_a": d.data_a,
                "data_b": d.data_b,
                "diff_fields": d.diff_fields,
                "match_score": float(d.match_score) if d.match_score else None,
                "explanation": d.explanation,
                "is_manual_override": d.is_manual_override,
                "reviewer_notes": d.reviewer_notes,
                "reviewed_at": d.reviewed_at,
                "created_at": d.created_at,
            }
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
    }


@router.get("/workspaces/{workspace_id}/discrepancies/{discrepancy_id}")
async def get_discrepancy(
    workspace_id: str,
    discrepancy_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    d = await _get_discrepancy_checked(discrepancy_id, workspace_id, db)
    return {
        "id": d.id,
        "job_id": d.job_id,
        "category": d.category,
        "status": d.status,
        "data_a": d.data_a,
        "data_b": d.data_b,
        "diff_fields": d.diff_fields,
        "match_score": float(d.match_score) if d.match_score else None,
        "explanation": d.explanation,
        "is_manual_override": d.is_manual_override,
        "reviewer_notes": d.reviewer_notes,
        "reviewed_by_id": d.reviewed_by_id,
        "reviewed_at": d.reviewed_at,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


@router.post("/workspaces/{workspace_id}/discrepancies/{discrepancy_id}/review")
async def review_discrepancy(
    workspace_id: str,
    discrepancy_id: str,
    body: DiscrepancyReviewRequest,
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    d = await _get_discrepancy_checked(discrepancy_id, workspace_id, db)

    action = body.action
    status_map = {
        "accept": DiscrepancyStatus.reviewed,
        "reject": DiscrepancyStatus.reviewed,
        "resolve": DiscrepancyStatus.resolved,
        "reopen": DiscrepancyStatus.reopened,
    }
    d.status = status_map[action]
    d.reviewer_notes = body.notes
    d.reviewed_by_id = member.user_id
    d.reviewed_at = datetime.now(timezone.utc)
    if action in ("accept", "reject"):
        d.is_manual_override = True

    await log_event(db, f"discrepancy.{action}", "discrepancy",
                    workspace_id=workspace_id, actor_id=member.user_id,
                    resource_id=discrepancy_id, metadata={"action": action, "notes": body.notes})
    await db.commit()
    return {"id": d.id, "status": d.status, "reviewed_at": d.reviewed_at}
