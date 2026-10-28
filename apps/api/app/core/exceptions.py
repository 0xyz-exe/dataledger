"""Custom exception types and global exception handlers."""
from fastapi import Request
from fastapi.responses import JSONResponse


class DataLedgerError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(DataLedgerError):
    def __init__(self, resource: str = "Resource"):
        super().__init__(f"{resource} not found", status_code=404)


class ForbiddenError(DataLedgerError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, status_code=403)


class UnauthorizedError(DataLedgerError):
    def __init__(self, message: str = "Not authenticated"):
        super().__init__(message, status_code=401)


class ConflictError(DataLedgerError):
    def __init__(self, message: str = "Conflict"):
        super().__init__(message, status_code=409)


class ValidationError(DataLedgerError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, status_code=422)


async def dataledger_exception_handler(request: Request, exc: DataLedgerError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "status_code": exc.status_code},
    )
