"""Audit logging service."""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import AuditLog


async def log_event(
    db: AsyncSession,
    action: str,
    resource_type: str,
    workspace_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Fire-and-forget audit log. Never raises — audit failures must not block business logic."""
    try:
        log = AuditLog(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            event_metadata={k: v for k, v in (metadata or {}).items() if k not in ("password", "token", "secret")},
            ip_address=ip_address,
        )
        db.add(log)
        await db.flush()
    except Exception:
        pass  # audit log failure must never break the request
