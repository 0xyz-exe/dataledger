"""Export / reporting endpoints."""
import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import get_workspace_member, require_role
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.models.models import Discrepancy, ReconciliationJob, WorkspaceMember, UserRole, DiscrepancyCategory

router = APIRouter(tags=["reports"])


def _check_formula_injection(value: str) -> str:
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _safe_csv_value(val: any) -> str:
    if val is None:
        return ""
    s = str(val)
    return _check_formula_injection(s)


@router.get("/workspaces/{workspace_id}/reconciliation/jobs/{job_id}/export")
async def export_results(
    workspace_id: str,
    job_id: str,
    format: str = Query("csv", pattern="^(csv|json)$"),
    filter: Optional[str] = Query(None, description="matched|unmatched|discrepancies|all"),
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ReconciliationJob).where(ReconciliationJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job or job.workspace_id != workspace_id:
        raise NotFoundError("Reconciliation job")

    # Build discrepancy query
    q = select(Discrepancy).where(Discrepancy.job_id == job_id)
    if filter == "matched":
        q = q.where(Discrepancy.category == DiscrepancyCategory.matched)
    elif filter == "unmatched":
        q = q.where(Discrepancy.category.in_([DiscrepancyCategory.missing_in_a, DiscrepancyCategory.missing_in_b]))
    elif filter == "discrepancies":
        q = q.where(Discrepancy.category != DiscrepancyCategory.matched)

    rows_result = await db.execute(q.order_by(Discrepancy.created_at))
    rows = rows_result.scalars().all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "category", "status", "explanation",
            "diff_fields", "match_score",
            "data_a", "data_b",
            "is_manual_override", "reviewer_notes", "reviewed_at"
        ])
        for d in rows:
            writer.writerow([
                _safe_csv_value(d.id),
                _safe_csv_value(d.category.value if d.category else ""),
                _safe_csv_value(d.status.value if d.status else ""),
                _safe_csv_value(d.explanation),
                _safe_csv_value(json.dumps(d.diff_fields)),
                _safe_csv_value(d.match_score),
                _safe_csv_value(json.dumps(d.data_a)),
                _safe_csv_value(json.dumps(d.data_b)),
                _safe_csv_value(d.is_manual_override),
                _safe_csv_value(d.reviewer_notes),
                _safe_csv_value(d.reviewed_at),
            ])
        output.seek(0)
        filename = f"dataledger-{job_id[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # JSON export
    export_data = {
        "report_id": f"rpt-{job_id[:8]}",
        "job_id": job_id,
        "job_name": job.name,
        "workspace_id": workspace_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filter": filter or "all",
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
                "category": d.category.value if d.category else None,
                "status": d.status.value if d.status else None,
                "explanation": d.explanation,
                "diff_fields": d.diff_fields,
                "match_score": float(d.match_score) if d.match_score else None,
                "data_a": d.data_a,
                "data_b": d.data_b,
            }
            for d in rows
        ],
    }
    filename = f"dataledger-{job_id[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    return StreamingResponse(
        iter([json.dumps(export_data, default=str, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
