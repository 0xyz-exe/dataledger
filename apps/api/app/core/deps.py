"""Dependency injection for auth and workspace access."""
from typing import Optional
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedError, ForbiddenError, NotFoundError
from app.models.models import User, WorkspaceMember, UserRole


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise UnauthorizedError("Invalid or expired token")
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found or inactive")
    return user


async def get_workspace_member(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceMember:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise ForbiddenError("Not a member of this workspace")
    return member


def require_role(*roles: UserRole):
    """Returns a dependency that enforces minimum role."""
    async def checker(member: WorkspaceMember = Depends(get_workspace_member)) -> WorkspaceMember:
        role_order = [UserRole.viewer, UserRole.analyst, UserRole.admin, UserRole.owner]
        min_idx = min(role_order.index(r) for r in roles)
        if role_order.index(member.role) < min_idx:
            raise ForbiddenError(f"Requires one of: {[r.value for r in roles]}")
        return member
    return checker
