"""
Reconciliation Engine — core matching logic.

Design:
- Deterministic: same input + config → same output.
- Explainable: every result has a human-readable explanation.
- Modular: strategies are pure functions, independently testable.
- Uses Decimal for all monetary arithmetic (never float).
- One-to-one matching enforced: a row cannot be reused once matched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from app.models.models import DiscrepancyCategory


ENGINE_VERSION = "1.0.0"

CANONICAL_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
]


# ── Value normalization ─────────────────────────────────────────────────────────

def normalize_string(value: Any, case_sensitive: bool = False) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s if case_sensitive else s.lower()


def parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace(" ", "")
    # Strip currency symbols
    s = re.sub(r"[^\d.\-]", "", s)
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date() if isinstance(value, datetime) else value
    s = str(value).strip()
    for fmt in CANONICAL_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def normalize_row(row: dict, config: dict) -> dict:
    """Apply normalization config to a canonical row."""
    result = {}
    for k, v in row.items():
        if isinstance(v, str):
            if config.get("strip_whitespace", True):
                v = v.strip()
            if config.get("lowercase_strings", False):
                v = v.lower()
            if config.get("empty_to_null", True) and not v:
                v = None
        result[k] = v
    return result


# ── Match result ────────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    category: DiscrepancyCategory
    row_a_idx: Optional[int]
    row_b_idx: Optional[int]
    data_a: Optional[dict]
    data_b: Optional[dict]
    diff_fields: list[str]
    explanation: str
    match_score: float = 1.0
    is_ambiguous: bool = False


# ── Matching strategies ─────────────────────────────────────────────────────────

def _exact_match_key(row: dict, match_fields: list[str], case_sensitive: bool) -> Optional[tuple]:
    parts = []
    for f in match_fields:
        val = normalize_string(row.get(f), case_sensitive=case_sensitive)
        if val is None:
            return None  # null field → cannot form a match key
        parts.append(val)
    return tuple(parts)


def _build_index(rows: list[dict], match_fields: list[str], case_sensitive: bool) -> dict[tuple, list[int]]:
    """Build hash index: key → list of row indices (supports duplicates)."""
    index: dict[tuple, list[int]] = {}
    for i, row in enumerate(rows):
        key = _exact_match_key(row, match_fields, case_sensitive)
        if key is not None:
            index.setdefault(key, []).append(i)
    return index


def _compare_amounts(a_val: Any, b_val: Any, tolerance: Optional[Decimal]) -> tuple[bool, Optional[str]]:
    a = parse_decimal(a_val)
    b = parse_decimal(b_val)
    if a is None or b is None:
        return False, "Amount could not be parsed"
    diff = abs(a - b)
    if tolerance is not None and diff <= tolerance:
        return True, None
    if diff == 0:
        return True, None
    return False, f"Amount differs by {diff} (A={a}, B={b})"


def _compare_dates(a_val: Any, b_val: Any, tolerance_days: int) -> tuple[bool, Optional[str]]:
    a = parse_date(a_val)
    b = parse_date(b_val)
    if a is None or b is None:
        return False, "Date could not be parsed"
    delta = abs((a - b).days)
    if delta <= tolerance_days:
        return True, None
    return False, f"Date differs by {delta} days (A={a}, B={b})"


def _describe_diff(data_a: dict, data_b: dict, amount_field: str, date_field: str,
                   amount_tol: Optional[Decimal], date_tol: int) -> tuple[list[str], str]:
    diff_fields: list[str] = []
    explanations: list[str] = []

    if amount_field in data_a and amount_field in data_b:
        ok, msg = _compare_amounts(data_a.get(amount_field), data_b.get(amount_field), amount_tol)
        if not ok:
            diff_fields.append(amount_field)
            explanations.append(msg or "Amount mismatch")

    if date_field in data_a and date_field in data_b:
        ok, msg = _compare_dates(data_a.get(date_field), data_b.get(date_field), date_tol)
        if not ok:
            diff_fields.append(date_field)
            explanations.append(msg or "Date mismatch")

    # Generic field diffs for other fields
    for k in set(data_a) | set(data_b):
        if k in (amount_field, date_field):
            continue
        va = normalize_string(data_a.get(k))
        vb = normalize_string(data_b.get(k))
        if va != vb:
            diff_fields.append(k)
            explanations.append(f"Field '{k}' differs (A={data_a.get(k)!r}, B={data_b.get(k)!r})")

    return diff_fields, "; ".join(explanations) if explanations else "Fields match"


# ── Main engine ─────────────────────────────────────────────────────────────────

def run_reconciliation(
    rows_a: list[dict],
    rows_b: list[dict],
    rules: dict,
) -> list[MatchResult]:
    """
    Reconcile two lists of canonical row dicts.

    rules keys:
        match_fields: list[str]
        strategy: "exact" | "composite"
        amount_tolerance: str | None  (decimal)
        date_tolerance_days: int
        case_sensitive: bool
        null_handling: "exclude" | "treat_as_empty"
        amount_field: str
        date_field: str
    """
    match_fields: list[str] = rules.get("match_fields", [])
    case_sensitive: bool = rules.get("case_sensitive", False)
    amount_tol_str: Optional[str] = rules.get("amount_tolerance")
    amount_tol: Optional[Decimal] = Decimal(amount_tol_str) if amount_tol_str else None
    date_tol: int = int(rules.get("date_tolerance_days", 0))
    amount_field: str = rules.get("amount_field", "amount")
    date_field: str = rules.get("date_field", "transaction_date")
    normalization = rules.get("normalization_config") or {}

    # Normalize
    norm_a = [normalize_row(r, normalization) for r in rows_a]
    norm_b = [normalize_row(r, normalization) for r in rows_b]

    results: list[MatchResult] = []
    used_a: set[int] = set()
    used_b: set[int] = set()

    # Build hash index on B
    index_b = _build_index(norm_b, match_fields, case_sensitive)

    # Pass 1: match A → B
    for i, row_a in enumerate(norm_a):
        key = _exact_match_key(row_a, match_fields, case_sensitive)
        if key is None:
            # Cannot form match key
            results.append(MatchResult(
                category=DiscrepancyCategory.invalid_record,
                row_a_idx=i, row_b_idx=None,
                data_a=rows_a[i], data_b=None,
                diff_fields=match_fields,
                explanation=f"Row {i+1} in A: match field(s) are null/empty.",
            ))
            used_a.add(i)
            continue

        candidates = index_b.get(key, [])
        # Filter already-used B rows
        available = [j for j in candidates if j not in used_b]

        if not available:
            # No match found
            results.append(MatchResult(
                category=DiscrepancyCategory.missing_in_b,
                row_a_idx=i, row_b_idx=None,
                data_a=rows_a[i], data_b=None,
                diff_fields=[],
                explanation=f"No matching record found in source B for key {key}.",
            ))
            used_a.add(i)
            continue

        if len(available) > 1:
            # Ambiguous: multiple candidates
            results.append(MatchResult(
                category=DiscrepancyCategory.ambiguous_match,
                row_a_idx=i, row_b_idx=None,
                data_a=rows_a[i], data_b=None,
                diff_fields=[],
                explanation=f"Multiple candidates in B match key {key}. Manual review required.",
                is_ambiguous=True,
            ))
            used_a.add(i)
            continue

        j = available[0]
        row_b = norm_b[j]
        diff_fields, explanation = _describe_diff(row_a, row_b, amount_field, date_field, amount_tol, date_tol)

        if not diff_fields:
            category = DiscrepancyCategory.matched
            explanation = f"Exact match on {match_fields}."
            match_score = 1.0
        else:
            # Classify primary discrepancy type
            if amount_field in diff_fields and date_field in diff_fields:
                category = DiscrepancyCategory.amount_mismatch  # report primary first
            elif amount_field in diff_fields:
                category = DiscrepancyCategory.amount_mismatch
            elif date_field in diff_fields:
                category = DiscrepancyCategory.date_mismatch
            else:
                category = DiscrepancyCategory.reference_mismatch
            match_score = max(0.0, 1.0 - len(diff_fields) * 0.2)

        results.append(MatchResult(
            category=category,
            row_a_idx=i, row_b_idx=j,
            data_a=rows_a[i], data_b=rows_b[j],
            diff_fields=diff_fields,
            explanation=explanation,
            match_score=match_score,
        ))
        used_a.add(i)
        used_b.add(j)

    # Pass 2: remaining B rows = missing in A
    for j, row_b in enumerate(norm_b):
        if j not in used_b:
            results.append(MatchResult(
                category=DiscrepancyCategory.missing_in_a,
                row_a_idx=None, row_b_idx=j,
                data_a=None, data_b=rows_b[j],
                diff_fields=[],
                explanation=f"Record in source B has no match in source A.",
            ))

    return results
