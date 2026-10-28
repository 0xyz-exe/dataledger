"""Workspace management endpoints."""
import re
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_member, require_role
from app.core.exceptions import NotFoundError, ConflictError, ForbiddenError
from app.models.models import User, Workspace, WorkspaceMember, UserRole
from app.schemas.schemas import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, WorkspaceMemberResponse, InviteMemberRequest
from app.services.audit import log_event

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"{slug[:40]}-{str(uuid.uuid4())[:8]}"


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id, Workspace.is_active == True)
    )
    return result.scalars().all()


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = Workspace(name=body.name, slug=_slugify(body.name), description=body.description)
    db.add(workspace)
    await db.flush()
    member = WorkspaceMember(workspace_id=workspace.id, user_id=current_user.id, role=UserRole.owner)
    db.add(member)
    await log_event(db, "workspace.create", "workspace", workspace_id=workspace.id,
                    actor_id=current_user.id, resource_id=workspace.id)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise NotFoundError("Workspace")
    return ws


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    member: WorkspaceMember = Depends(require_role(UserRole.admin, UserRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise NotFoundError("Workspace")
    if body.name is not None:
        ws.name = body.name
    if body.description is not None:
        ws.description = body.description
    await log_event(db, "workspace.update", "workspace", workspace_id=workspace_id,
                    actor_id=member.user_id, resource_id=workspace_id)
    await db.commit()
    await db.refresh(ws)
    return ws


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_members(
    workspace_id: str,
    member: WorkspaceMember = Depends(get_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    )
    return result.scalars().all()
