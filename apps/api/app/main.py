"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.config import settings
from app.core.database import create_all_tables
from app.core.exceptions import DataLedgerError, dataledger_exception_handler
from app.api.v1 import auth, workspaces, datasets, reconciliation, discrepancies, dashboard, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev mode). Production: run alembic upgrade head.
    await create_all_tables()
    yield


app = FastAPI(
    title="DataLedger API",
    description="Open-Source Business Data Reconciliation Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(DataLedgerError)
async def handle_dataledger_error(request: Request, exc: DataLedgerError):
    return await dataledger_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Validation failed", "details": exc.errors()},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    # Never expose stack traces in production
    if settings.APP_DEBUG:
        import traceback
        detail = traceback.format_exc()
    else:
        detail = "An unexpected error occurred"
    return JSONResponse(status_code=500, content={"error": detail if settings.APP_DEBUG else "Internal server error"})


# API v1 prefix
PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(workspaces.router, prefix=PREFIX)
app.include_router(datasets.router, prefix=PREFIX)
app.include_router(reconciliation.router, prefix=PREFIX)
app.include_router(discrepancies.router, prefix=PREFIX)
app.include_router(dashboard.router, prefix=PREFIX)
app.include_router(reports.router, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
