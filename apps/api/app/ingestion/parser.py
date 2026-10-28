"""Data ingestion: parse CSV, XLSX, JSON files into DatasetRows."""
import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
import aiofiles
import pandas as pd
from fastapi import UploadFile

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}
CHUNK_SIZE = 1000  # rows per DB batch


def _safe_filename(original: str) -> str:
    """Strip path components and unsafe chars from uploaded filenames."""
    name = Path(original).name
    name = re.sub(r"[^\w.\-]", "_", name)
    return f"{uuid.uuid4().hex}_{name[:100]}"


def _detect_type(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        # Try date
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                datetime.strptime(value.strip(), fmt)
                return "date"
            except ValueError:
                pass
        # Try number
        try:
            Decimal(value.replace(",", "").replace(" ", ""))
            return "number"
        except InvalidOperation:
            pass
    return "string"


def _detect_schema(rows: list[dict]) -> dict:
    """Infer column types from first 100 rows."""
    if not rows:
        return {}
    sample = rows[:100]
    columns = list(rows[0].keys())
    schema: dict[str, dict] = {}
    for col in columns:
        type_counts: dict[str, int] = {}
        for row in sample:
            t = _detect_type(row.get(col))
            type_counts[t] = type_counts.get(t, 0) + 1
        dominant = max(type_counts, key=lambda k: type_counts[k])
        schema[col] = {"type": dominant, "nullable": type_counts.get("null", 0) > 0}
    return schema


def _check_csv_formula_injection(value: Any) -> Any:
    """Neutralize CSV formula injection: prefix dangerous chars."""
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _normalize_row(row: dict) -> dict:
    return {k: _check_csv_formula_injection(v) for k, v in row.items()}


async def parse_upload(file: UploadFile, upload_dir: str) -> dict:
    """
    Save file securely, parse it, return:
    {internal_path, original_filename, rows, schema, total_rows, parse_errors}
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"File exceeds maximum size of {MAX_FILE_SIZE // (1024*1024)} MB")

    safe_name = _safe_filename(file.filename or "upload")
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    internal_path = str(Path(upload_dir) / safe_name)

    async with aiofiles.open(internal_path, "wb") as f:
        await f.write(content)

    parse_errors: list[str] = []
    rows: list[dict] = []

    if ext == ".csv":
        try:
            text = content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for i, row in enumerate(reader):
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
                if i >= 100_000:
                    parse_errors.append("File truncated at 100,000 rows")
                    break
        except Exception as e:
            parse_errors.append(f"CSV parse error: {e}")

    elif ext in (".xlsx", ".xls"):
        try:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", nrows=100_000)
            rows = df.where(pd.notnull(df), None).to_dict(orient="records")
            # Convert non-serializable types
            for row in rows:
                for k, v in row.items():
                    if isinstance(v, (pd.Timestamp,)):
                        row[k] = v.isoformat()
                    elif isinstance(v, float) and pd.isna(v):
                        row[k] = None
        except Exception as e:
            parse_errors.append(f"XLSX parse error: {e}")

    elif ext == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, list):
                rows = data[:100_000]
            elif isinstance(data, dict):
                # Support {data: [...]} or flat object
                for key in ("data", "records", "rows", "items"):
                    if key in data and isinstance(data[key], list):
                        rows = data[key][:100_000]
                        break
                else:
                    rows = [data]
            else:
                parse_errors.append("JSON must be an array or object")
        except Exception as e:
            parse_errors.append(f"JSON parse error: {e}")

    schema = _detect_schema(rows)
    normalized = [_normalize_row(r) for r in rows]

    return {
        "internal_path": internal_path,
        "original_filename": file.filename,
        "rows": normalized,
        "schema": schema,
        "total_rows": len(normalized),
        "parse_errors": parse_errors,
    }


def validate_rows(rows: list[dict], schema: dict, column_mapping: dict) -> dict:
    """
    Validate and classify rows. Returns:
    {valid_rows, invalid_rows, duplicate_candidates, validation_errors, canonical_rows}
    """
    valid: list[dict] = []
    invalid: list[dict] = []
    errors: list[dict] = []
    seen_keys: set[str] = set()
    duplicates = 0

    canonical_field_names = set(column_mapping.values())

    for i, row in enumerate(rows):
        row_errors: list[str] = []

        # Build canonical row
        canonical: dict = {}
        for src_col, canon_field in column_mapping.items():
            val = row.get(src_col)
            canonical[canon_field] = val

        # Check required fields (non-null canonical fields)
        for field, val in canonical.items():
            if val is None or (isinstance(val, str) and not val.strip()):
                row_errors.append(f"Field '{field}' is empty")

        # Duplicate detection via composite key of all canonical fields
        key = str(sorted(canonical.items()))
        if key in seen_keys:
            duplicates += 1
            row_errors.append("Possible duplicate row")
        else:
            seen_keys.add(key)

        if row_errors:
            invalid.append({"row_number": i + 1, "data": row, "errors": row_errors})
            errors.append({"row": i + 1, "errors": row_errors})
        else:
            valid.append({"row_number": i + 1, "raw": row, "canonical": canonical})

    return {
        "valid_rows": valid,
        "invalid_rows": invalid,
        "duplicate_candidates": duplicates,
        "validation_errors": errors,
    }
