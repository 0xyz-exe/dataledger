"""Dataset management endpoints."""
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_member, require_role
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.core.config import settings
from app.models.models import User, Dataset, DatasetRow, ImportJob, WorkspaceMember, UserRole, ImportStatus
from app.schemas.schemas import DatasetCreate, DatasetResponse, ColumnMappingRequest, ImportJobResponse
from app.ingestion.parser import parse_upload, validate_rows
from app.services.audit import log_event
from datetime import datetime, timezone

router = APIRouter(tags=["datasets"])


def _check_workspace_dataset(dataset: Dataset, workspace_id: str) -> None:
    """Prevent IDOR: ensure dataset belongs to the requested workspace."""
    if dataset.workspace_id != workspace_id:
        raise ForbiddenError("Dataset not found in this workspace")


@router.get("/workspaces/{workspace_id}/datasets", response_model=list[DatasetResponse])
async def list_datasets(
    workspace_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dataset).where(Dataset.workspace_id == workspace_id).order_by(Dataset.created_at.desc())
    )
    return result.scalars().all()


@router.post("/workspaces/{workspace_id}/datasets", response_model=DatasetResponse, status_code=201)
async def create_dataset(
    workspace_id: str,
    body: DatasetCreate,
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    dataset = Dataset(
        workspace_id=workspace_id,
        created_by_id=member.user_id,
        name=body.name,
        description=body.description,
    )
    db.add(dataset)
    await log_event(db, "dataset.create", "dataset", workspace_id=workspace_id,
                    actor_id=member.user_id, resource_id=dataset.id)
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("/workspaces/{workspace_id}/datasets/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    workspace_id: str,
    dataset_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise NotFoundError("Dataset")
    _check_workspace_dataset(dataset, workspace_id)
    return dataset


@router.delete("/workspaces/{workspace_id}/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    workspace_id: str,
    dataset_id: str,
    member: WorkspaceMember = Depends(require_role(UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise NotFoundError("Dataset")
    _check_workspace_dataset(dataset, workspace_id)
    await db.delete(dataset)
    await log_event(db, "dataset.delete", "dataset", workspace_id=workspace_id,
                    actor_id=member.user_id, resource_id=dataset_id)
    await db.commit()


@router.post("/workspaces/{workspace_id}/datasets/{dataset_id}/upload", response_model=dict)
async def upload_file(
    workspace_id: str,
    dataset_id: str,
    file: UploadFile = File(...),
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Step 1: Upload file, parse it, return schema + preview."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise NotFoundError("Dataset")
    _check_workspace_dataset(dataset, workspace_id)

    try:
        parsed = await parse_upload(file, settings.UPLOAD_DIR)
    except ValueError as e:
        raise ValidationError(str(e))

    # Store schema and path, mark as pending mapping
    dataset.original_filename = parsed["original_filename"]
    dataset.internal_path = parsed["internal_path"]
    dataset.schema_definition = parsed["schema"]
    dataset.import_status = ImportStatus.pending
    await db.commit()
    await db.refresh(dataset)

    preview = parsed["rows"][:20]
    return {
        "dataset_id": dataset_id,
        "original_filename": parsed["original_filename"],
        "total_rows": parsed["total_rows"],
        "columns": list(parsed["schema"].keys()),
        "schema": parsed["schema"],
        "preview": preview,
        "parse_errors": parsed["parse_errors"],
    }


@router.post("/workspaces/{workspace_id}/datasets/{dataset_id}/import", response_model=ImportJobResponse, status_code=201)
async def import_dataset(
    workspace_id: str,
    dataset_id: str,
    mapping: ColumnMappingRequest,
    background_tasks: BackgroundTasks,
    member: WorkspaceMember = Depends(require_role(UserRole.analyst, UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    """Step 2: Confirm column mapping and import rows."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise NotFoundError("Dataset")
    _check_workspace_dataset(dataset, workspace_id)
    if not dataset.internal_path:
        raise ValidationError("No file uploaded yet. Use /upload first.")

    # Save mapping
    dataset.column_mapping = mapping.mapping
    dataset.import_status = ImportStatus.processing

    import_job = ImportJob(dataset_id=dataset_id)
    db.add(import_job)
    await db.flush()
    job_id = import_job.id

    await db.commit()

    # Run in background
    background_tasks.add_task(
        _run_import,
        dataset_id=dataset_id,
        job_id=job_id,
        internal_path=dataset.internal_path,
        schema=dataset.schema_definition or {},
        column_mapping=mapping.mapping,
        workspace_id=workspace_id,
        actor_id=member.user_id,
    )

    await db.refresh(import_job)
    return import_job


async def _run_import(
    dataset_id: str, job_id: str, internal_path: str,
    schema: dict, column_mapping: dict, workspace_id: str, actor_id: str
) -> None:
    """Background task: parse file, validate, persist rows."""
    import csv, io, json
    from pathlib import Path
    from app.core.database import AsyncSessionLocal
    from app.models.models import DatasetRow

    async with AsyncSessionLocal() as db:
        try:
            # Re-read the file (already saved)
            ext = Path(internal_path).suffix.lower()
            rows: list[dict] = []

            if ext == ".csv":
                with open(internal_path, "r", encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
            elif ext in (".xlsx", ".xls"):
                import pandas as pd
                df = pd.read_excel(internal_path, engine="openpyxl")
                rows = df.where(pd.notnull(df), None).to_dict(orient="records")
            elif ext == ".json":
                with open(internal_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                rows = data if isinstance(data, list) else data.get("data", [data])

            validated = validate_rows(rows, schema, column_mapping)

            # Bulk insert valid rows
            result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
            dataset = result.scalar_one_or_none()
            if not dataset:
                return

            all_db_rows = []
            for item in validated["valid_rows"]:
                all_db_rows.append(DatasetRow(
                    dataset_id=dataset_id,
                    row_number=item["row_number"],
                    raw_data=item["raw"],
                    canonical_data=item["canonical"],
                    is_valid=True,
                ))
            for item in validated["invalid_rows"]:
                all_db_rows.append(DatasetRow(
                    dataset_id=dataset_id,
                    row_number=item["row_number"],
                    raw_data=item["data"],
                    is_valid=False,
                    validation_errors=item["errors"],
                ))

            db.add_all(all_db_rows)

            # Update job and dataset
            result2 = await db.execute(select(ImportJob).where(ImportJob.id == job_id))
            job = result2.scalar_one()
            job.status = ImportStatus.completed
            job.total_rows = len(rows)
            job.valid_rows = len(validated["valid_rows"])
            job.invalid_rows = len(validated["invalid_rows"])
            job.duplicate_candidates = validated["duplicate_candidates"]
            job.validation_report = {"errors": validated["validation_errors"][:100]}
            job.completed_at = datetime.now(timezone.utc)

            dataset.import_status = ImportStatus.completed
            dataset.row_count = len(validated["valid_rows"])

            await log_event(db, "dataset.import", "dataset", workspace_id=workspace_id,
                            actor_id=actor_id, resource_id=dataset_id,
                            metadata={"total": len(rows), "valid": len(validated["valid_rows"])})
            await db.commit()

        except Exception as e:
            async with AsyncSessionLocal() as db2:
                result3 = await db2.execute(select(ImportJob).where(ImportJob.id == job_id))
                job = result3.scalar_one_or_none()
                if job:
                    job.status = ImportStatus.failed
                    job.error_message = str(e)
                result4 = await db2.execute(select(Dataset).where(Dataset.id == dataset_id))
                ds = result4.scalar_one_or_none()
                if ds:
                    ds.import_status = ImportStatus.failed
                    ds.import_error = str(e)
                await db2.commit()


@router.get("/workspaces/{workspace_id}/datasets/{dataset_id}/preview")
async def preview_dataset(
    workspace_id: str,
    dataset_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise NotFoundError("Dataset")
    _check_workspace_dataset(dataset, workspace_id)

    offset = (page - 1) * page_size
    rows_result = await db.execute(
        select(DatasetRow)
        .where(DatasetRow.dataset_id == dataset_id, DatasetRow.is_valid == True)
        .order_by(DatasetRow.row_number)
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.scalars().all()
    total_result = await db.execute(
        select(func.count()).where(DatasetRow.dataset_id == dataset_id, DatasetRow.is_valid == True)
    )
    total = total_result.scalar()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [{"row_number": r.row_number, "data": r.canonical_data or r.raw_data} for r in rows],
    }


@router.get("/workspaces/{workspace_id}/datasets/{dataset_id}/import-jobs", response_model=list[ImportJobResponse])
async def list_import_jobs(
    workspace_id: str,
    dataset_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise NotFoundError("Dataset")
    _check_workspace_dataset(dataset, workspace_id)

    jobs_result = await db.execute(
        select(ImportJob).where(ImportJob.dataset_id == dataset_id).order_by(ImportJob.created_at.desc())
    )
    return jobs_result.scalars().all()
