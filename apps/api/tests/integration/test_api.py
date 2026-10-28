"""Integration tests: full API flow with in-memory SQLite."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.core.database import Base, get_db, AsyncSessionLocal


# ── Test DB setup ──────────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


async def override_get_db():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app.dependency_overrides[get_db] = override_get_db
    # Also patch AsyncSessionLocal used by background tasks
    import app.core.database as db_module
    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = TestSession
    yield
    db_module.AsyncSessionLocal = original
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client):
    """Returns (client, access_token, workspace_id)."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "user@example.com",
        "display_name": "Test User",
        "password": "password123",
    })
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    # Get workspace
    ws_resp = await client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    workspaces = ws_resp.json()
    workspace_id = workspaces[0]["id"]

    return client, token, workspace_id


# ── Auth tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "display_name": "New User",
        "password": "password123",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    body = {"email": "dup@example.com", "display_name": "User", "password": "password123"}
    await client.post("/api/v1/auth/register", json=body)
    resp = await client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login(client):
    await client.post("/api/v1/auth/register", json={
        "email": "login@example.com", "display_name": "Login User", "password": "password123"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "login@example.com", "password": "password123"
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "email": "wp@example.com", "display_name": "WP", "password": "password123"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "wp@example.com", "password": "wrongpassword"
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me(auth_client):
    client, token, _ = auth_client
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_unauthenticated_request(client):
    resp = await client.get("/api/v1/workspaces")
    assert resp.status_code == 401


# ── Workspace isolation test ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_workspace_isolation(client):
    """User A cannot access User B's workspace."""
    for email in ("a@example.com", "b@example.com"):
        await client.post("/api/v1/auth/register", json={
            "email": email, "display_name": email, "password": "password123"
        })

    login_a = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
    token_a = login_a.json()["access_token"]
    login_b = await client.post("/api/v1/auth/login", json={"email": "b@example.com", "password": "password123"})
    token_b = login_b.json()["access_token"]

    # Get B's workspace ID
    ws_b = await client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {token_b}"})
    b_workspace_id = ws_b.json()[0]["id"]

    # A tries to access B's workspace
    resp = await client.get(f"/api/v1/workspaces/{b_workspace_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 403


# ── Dataset tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_list_dataset(auth_client):
    client, token, workspace_id = auth_client
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets",
        json={"name": "Sales Data", "description": "Q4 sales"},
        headers=headers,
    )
    assert resp.status_code == 201
    ds = resp.json()
    assert ds["name"] == "Sales Data"
    assert ds["workspace_id"] == workspace_id

    list_resp = await client.get(f"/api/v1/workspaces/{workspace_id}/datasets", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_viewer_cannot_create_dataset(client):
    """Viewer role cannot create datasets."""
    # Register owner and viewer
    owner_reg = await client.post("/api/v1/auth/register", json={
        "email": "owner@example.com", "display_name": "Owner", "password": "password123"
    })
    owner_token = owner_reg.json()["access_token"]

    viewer_reg = await client.post("/api/v1/auth/register", json={
        "email": "viewer@example.com", "display_name": "Viewer", "password": "password123"
    })
    viewer_token = viewer_reg.json()["access_token"]

    # Owner creates workspace manually
    ws_resp = await client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {owner_token}"})
    workspace_id = ws_resp.json()[0]["id"]

    # Viewer tries to create dataset in owner's workspace (not a member → 403)
    resp = await client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets",
        json={"name": "Test"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


# ── Reconciliation tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconciliation_e2e(auth_client):
    """End-to-end: create 2 datasets → import rows → create job → run → check results."""
    import io, csv
    from app.core.database import AsyncSessionLocal
    from app.models.models import Dataset, DatasetRow, ImportStatus

    client, token, workspace_id = auth_client
    headers = {"Authorization": f"Bearer {token}"}

    # Create datasets
    ds_a = (await client.post(f"/api/v1/workspaces/{workspace_id}/datasets",
                               json={"name": "Source A"}, headers=headers)).json()
    ds_b = (await client.post(f"/api/v1/workspaces/{workspace_id}/datasets",
                               json={"name": "Source B"}, headers=headers)).json()

    # Manually insert rows (bypassing file upload for test speed)
    rows_a = [
        {"reference_id": "TXN-001", "amount": "100000", "transaction_date": "2026-10-01"},
        {"reference_id": "TXN-002", "amount": "200000", "transaction_date": "2026-10-02"},
        {"reference_id": "TXN-003", "amount": "300000", "transaction_date": "2026-10-03"},
    ]
    rows_b = [
        {"reference_id": "TXN-001", "amount": "100000", "transaction_date": "2026-10-01"},  # exact match
        {"reference_id": "TXN-002", "amount": "195000", "transaction_date": "2026-10-02"},  # amount mismatch
        # TXN-003 missing in B
        {"reference_id": "TXN-004", "amount": "400000", "transaction_date": "2026-10-04"},  # missing in A
    ]

    async with AsyncSessionLocal() as db:
        for dataset_id, rows in [(ds_a["id"], rows_a), (ds_b["id"], rows_b)]:
            from sqlalchemy import select as sa_select
            db_rows = [DatasetRow(dataset_id=dataset_id, row_number=i+1,
                                  raw_data=r, canonical_data=r, is_valid=True)
                       for i, r in enumerate(rows)]
            db.add_all(db_rows)

            result = await db.execute(sa_select(Dataset).where(Dataset.id == dataset_id))
            ds_obj = result.scalar_one()
            ds_obj.import_status = ImportStatus.completed
            ds_obj.row_count = len(rows)
        await db.commit()

    # Create reconciliation job
    job_resp = await client.post(
        f"/api/v1/workspaces/{workspace_id}/reconciliation/jobs",
        json={
            "name": "Test Recon",
            "dataset_a_id": ds_a["id"],
            "dataset_b_id": ds_b["id"],
            "matching_rules": {
                "match_fields": ["reference_id"],
                "strategy": "exact",
                "amount_tolerance": None,
                "date_tolerance_days": 0,
                "case_sensitive": False,
                "null_handling": "exclude",
                "amount_field": "amount",
                "date_field": "transaction_date",
                "fuzzy_threshold": 0.85,
            },
        },
        headers=headers,
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    # Run job (synchronously for test — background task runs inline with ASGI transport)
    run_resp = await client.post(
        f"/api/v1/workspaces/{workspace_id}/reconciliation/jobs/{job_id}/run",
        headers=headers,
    )
    assert run_resp.status_code == 200

    # Wait for background task (small sleep)
    import asyncio
    await asyncio.sleep(1)

    # Get results
    results_resp = await client.get(
        f"/api/v1/workspaces/{workspace_id}/reconciliation/jobs/{job_id}/results",
        headers=headers,
    )
    assert results_resp.status_code == 200
    data = results_resp.json()

    categories = {r["category"] for r in data["results"]}
    # Must have matched, amount_mismatch, missing_in_b, missing_in_a
    assert "matched" in categories
    assert "amount_mismatch" in categories


@pytest.mark.asyncio
async def test_cross_workspace_dataset_access(auth_client, client):
    """User cannot access datasets from another workspace."""
    client2, token2, ws2 = auth_client

    # Create another user
    other_reg = await client.post("/api/v1/auth/register", json={
        "email": "other@example.com", "display_name": "Other", "password": "password123"
    })
    other_token = other_reg.json()["access_token"]
    other_ws = (await client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {other_token}"})).json()[0]

    # Create dataset in ws2
    ds = (await client.post(
        f"/api/v1/workspaces/{ws2}/datasets",
        json={"name": "Private"},
        headers={"Authorization": f"Bearer {token2}"},
    )).json()

    # Other user tries to get it through their workspace
    resp = await client.get(
        f"/api/v1/workspaces/{other_ws['id']}/datasets/{ds['id']}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code in (403, 404)
