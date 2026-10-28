"""Reconciliation job API endpoints."""
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import get_workspace_member, require_role
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError, ConflictError
from app.models.models import (
    ReconciliationJob, Dataset, DatasetRow, Discrepancy,
    WorkspaceMember, UserRole, JobStatus, DiscrepancyCategory, DiscrepancyStatus
)
from app.schemas.schemas import ReconciliationJobCreate, ReconciliationJobResponse, DiscrepancyResponse, DiscrepancyReviewRequest
from app.reconciliation.engine import run_reconciliation, ENGINE_VERSION
from app.services.audit import log_event

router = APIRouter(tags=["reconciliation"])


def _check_workspace_job(job: ReconciliationJob, workspace_id: str) -> None:
    if job.workspace_id != workspace_id:
        raise ForbiddenError("Job not found in this workspace")


@router.get("/workspaces/{workspace_id}/reconciliation/jobs", response_model=list[ReconciliationJobResponse])
async def list_jobs(
    workspace_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReconciliationJob)
        .where(ReconciliationJob.workspace_id == workspace_id)
        .order_by(ReconciliationJob.created_at.desc())
    )
    return result.scalars().all()


@router.post("/workspaces/{workspace_id}/reconciliation/jobs", response_model=ReconciliationJobResponse, status_code=201)
async def create_job(
    workspace_id: str,
    body: ReconciliationJobCreate,
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    # Validate datasets belong to workspace
    for ds_id in (body.dataset_a_id, body.dataset_b_id):
        result = await db.execute(select(Dataset).where(Dataset.id == ds_id))
        ds = result.scalar_one_or_none()
        if not ds or ds.workspace_id != workspace_id:
            raise NotFoundError(f"Dataset {ds_id}")

    job = ReconciliationJob(
        workspace_id=workspace_id,
        created_by_id=member.user_id,
        name=body.name,
        description=body.description,
        dataset_a_id=body.dataset_a_id,
        dataset_b_id=body.dataset_b_id,
        matching_rules=body.matching_rules.model_dump(),
        normalization_config=body.normalization_config,
        engine_version=ENGINE_VERSION,
    )
    db.add(job)
    await log_event(db, "reconciliation.create", "reconciliation_job", workspace_id=workspace_id,
                    actor_id=member.user_id, resource_id=job.id)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/workspaces/{workspace_id}/reconciliation/jobs/{job_id}", response_model=ReconciliationJobResponse)
async def get_job(
    workspace_id: str,
    job_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Reconciliation job")
    _check_workspace_job(job, workspace_id)
    return job


@router.post("/workspaces/{workspace_id}/reconciliation/jobs/{job_id}/run", response_model=ReconciliationJobResponse)
async def run_job(
    workspace_id: str,
    job_id: str,
    background_tasks: BackgroundTasks,
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Reconciliation job")
    _check_workspace_job(job, workspace_id)

    if job.status in (JobStatus.running, JobStatus.queued):
        raise ConflictError("Job is already running")
    if job.status == JobStatus.completed:
        raise ConflictError("Job already completed. Create a new job to re-run.")

    job.status = JobStatus.queued
    job.started_at = datetime.now(timezone.utc)
    await log_event(db, "reconciliation.run", "reconciliation_job", workspace_id=workspace_id,
                    actor_id=member.user_id, resource_id=job_id)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _execute_reconciliation,
        job_id=job_id,
        workspace_id=workspace_id,
        actor_id=member.user_id,
    )
    return job


@router.post("/workspaces/{workspace_id}/reconciliation/jobs/{job_id}/cancel", response_model=ReconciliationJobResponse)
async def cancel_job(
    workspace_id: str,
    job_id: str,
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Reconciliation job")
    _check_workspace_job(job, workspace_id)

    if job.status not in (JobStatus.draft, JobStatus.queued):
        raise ConflictError(f"Cannot cancel a job in status '{job.status.value}'")
    job.status = JobStatus.cancelled
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/workspaces/{workspace_id}/reconciliation/jobs/{job_id}/results")
async def get_results(
    workspace_id: str,
    job_id: str,
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Reconciliation job")
    _check_workspace_job(job, workspace_id)

    q = select(Discrepancy).where(Discrepancy.job_id == job_id)
    if category:
        try:
            cat = DiscrepancyCategory(category)
            q = q.where(Discrepancy.category == cat)
        except ValueError:
            raise ValidationError(f"Invalid category: {category}")

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar()

    rows_result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = rows_result.scalars().all()

    return {
        "job_id": job_id,
        "job_status": job.status,
        "summary": {
            "matched": job.matched_count,
            "unmatched": job.unmatched_count,
            "discrepancies": job.discrepancy_count,
            "total_processed": job.total_processed,
            "match_rate": round(job.matched_count / job.total_processed, 4) if job.total_processed else 0,
        },
        "results": [
            {
                "id": d.id,
                "category": d.category,
                "status": d.status,
                "data_a": d.data_a,
                "data_b": d.data_b,
                "diff_fields": d.diff_fields,
                "match_score": float(d.match_score) if d.match_score else None,
                "explanation": d.explanation,
            }
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _execute_reconciliation(job_id: str, workspace_id: str, actor_id: str) -> None:
    """Background task: run the reconciliation engine and persist results."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                return

            job.status = JobStatus.running
            await db.commit()

            # Load rows from both datasets
            rows_a_result = await db.execute(
                select(DatasetRow)
                .where(DatasetRow.dataset_id == job.dataset_a_id, DatasetRow.is_valid == True)
                .order_by(DatasetRow.row_number)
            )
            rows_b_result = await db.execute(
                select(DatasetRow)
                .where(DatasetRow.dataset_id == job.dataset_b_id, DatasetRow.is_valid == True)
                .order_by(DatasetRow.row_number)
            )
            rows_a = [r.canonical_data or r.raw_data for r in rows_a_result.scalars().all()]
            rows_b = [r.canonical_data or r.raw_data for r in rows_b_result.scalars().all()]

            # Run engine
            match_results = run_reconciliation(rows_a, rows_b, job.matching_rules)

            # Persist discrepancies
            matched = 0
            discrepancies: list[Discrepancy] = []
            for mr in match_results:
                d = Discrepancy(
                    job_id=job_id,
                    category=mr.category,
                    data_a=mr.data_a,
                    data_b=mr.data_b,
                    diff_fields=mr.diff_fields,
                    match_score=mr.match_score,
                    explanation=mr.explanation,
                )
                discrepancies.append(d)
                if mr.category == DiscrepancyCategory.matched:
                    matched += 1

            db.add_all(discrepancies)

            job.status = JobStatus.completed
            job.matched_count = matched
            job.total_processed = len(rows_a) + len(rows_b)
            job.unmatched_count = sum(
                1 for mr in match_results
                if mr.category in (DiscrepancyCategory.missing_in_a, DiscrepancyCategory.missing_in_b)
            )
            job.discrepancy_count = len(match_results) - matched
            job.completed_at = datetime.now(timezone.utc)

            if job.discrepancy_count > 0:
                job.status = JobStatus.completed_with_warnings

            await log_event(db, "reconciliation.complete", "reconciliation_job",
                            workspace_id=workspace_id, actor_id=actor_id, resource_id=job_id,
                            metadata={"matched": matched, "total": job.total_processed})
            await db.commit()

        except Exception as e:
            async with AsyncSessionLocal() as db2:
                result2 = await db2.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
                job2 = result2.scalar_one_or_none()
                if job2:
                    job2.status = JobStatus.failed
                    job2.error_message = str(e)
                    await db2.commit()
