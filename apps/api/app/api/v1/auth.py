"""Authentication endpoints."""
import re
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.deps import get_current_user
from app.models.models import User, Workspace, WorkspaceMember, UserRole
from app.schemas.schemas import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.services.audit import log_event

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:50] or "workspace"


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    user = User(
        email=body.email,
        display_name=body.display_name,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()  # get user.id

    # Create personal workspace
    slug = _slugify(body.display_name)
    workspace = Workspace(name=f"{body.display_name}'s Workspace", slug=f"{slug}-{user.id[:8]}")
    db.add(workspace)
    await db.flush()

    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=UserRole.owner)
    db.add(member)

    await log_event(db, "user.register", "user", actor_id=user.id, resource_id=user.id)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedError("Invalid credentials")

    await log_event(db, "user.login", "user", actor_id=user.id, resource_id=user.id,
                    ip_address=request.client.host if request.client else None)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
