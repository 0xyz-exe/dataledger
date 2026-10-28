"""Dashboard / analytics endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import get_workspace_member
from app.models.models import Dataset, ReconciliationJob, Discrepancy, AuditLog, WorkspaceMember, JobStatus, DiscrepancyStatus, DiscrepancyCategory, ImportStatus

router = APIRouter(tags=["dashboard"])


@router.get("/workspaces/{workspace_id}/dashboard")
async def dashboard(
    workspace_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    # Counts
    datasets = await db.execute(select(func.count()).where(Dataset.workspace_id == workspace_id))
    total_datasets = datasets.scalar()

    jobs = await db.execute(select(func.count()).where(ReconciliationJob.workspace_id == workspace_id))
    total_jobs = jobs.scalar()

    completed_jobs = await db.execute(
        select(func.count()).where(
            ReconciliationJob.workspace_id == workspace_id,
            ReconciliationJob.status.in_([JobStatus.completed, JobStatus.completed_with_warnings])
        )
    )

    failed_jobs = await db.execute(
        select(func.count()).where(
            ReconciliationJob.workspace_id == workspace_id,
            ReconciliationJob.status == JobStatus.failed,
        )
    )

    # Workspace job IDs for discrepancy queries
    ws_job_ids_q = select(ReconciliationJob.id).where(ReconciliationJob.workspace_id == workspace_id)

    matched = await db.execute(
        select(func.sum(ReconciliationJob.matched_count)).where(ReconciliationJob.workspace_id == workspace_id)
    )
    total_matched = matched.scalar() or 0

    unmatched = await db.execute(
        select(func.sum(ReconciliationJob.unmatched_count)).where(ReconciliationJob.workspace_id == workspace_id)
    )
    total_unmatched = unmatched.scalar() or 0

    pending_review = await db.execute(
        select(func.count()).where(
            Discrepancy.job_id.in_(ws_job_ids_q),
            Discrepancy.status == DiscrepancyStatus.open,
            Discrepancy.category != DiscrepancyCategory.matched,
        )
    )

    total_processed = total_matched + total_unmatched
    match_rate = round(total_matched / total_processed, 4) if total_processed else 0.0

    # Recent jobs (last 5)
    recent_jobs_r = await db.execute(
        select(ReconciliationJob)
        .where(ReconciliationJob.workspace_id == workspace_id)
        .order_by(ReconciliationJob.created_at.desc())
        .limit(5)
    )
    recent_jobs = [
        {"id": j.id, "name": j.name, "status": j.status, "created_at": j.created_at}
        for j in recent_jobs_r.scalars().all()
    ]

    # Category distribution
    cat_dist_r = await db.execute(
        select(Discrepancy.category, func.count())
        .where(Discrepancy.job_id.in_(ws_job_ids_q))
        .group_by(Discrepancy.category)
    )
    category_distribution = [{"category": cat, "count": cnt} for cat, cnt in cat_dist_r.all()]

    return {
        "total_datasets": total_datasets,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs.scalar(),
        "failed_jobs": failed_jobs.scalar(),
        "matched_records": total_matched,
        "unmatched_records": total_unmatched,
        "pending_review": pending_review.scalar(),
        "match_rate": match_rate,
        "match_rate_definition": "matched_records / (matched_records + unmatched_records) across all completed jobs in workspace",
        "recent_jobs": recent_jobs,
        "category_distribution": category_distribution,
    }


@router.get("/workspaces/{workspace_id}/audit-logs")
async def audit_logs(
    workspace_id: str,
    page: int = 1,
    page_size: int = 50,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    total_r = await db.execute(
        select(func.count()).where(AuditLog.workspace_id == workspace_id)
    )
    total = total_r.scalar()
    logs_r = await db.execute(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = logs_r.scalars().all()
    return {
        "items": [
            {
                "id": l.id,
                "actor_id": l.actor_id,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "metadata": l.event_metadata,
                "created_at": l.created_at,
            }
            for l in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
