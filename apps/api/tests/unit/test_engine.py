"""Unit tests for the reconciliation engine.

Tests are pure Python — no database, no HTTP.
"""
import pytest
from decimal import Decimal
from app.reconciliation.engine import (
    run_reconciliation,
    normalize_string, parse_decimal, parse_date,
    normalize_row,
)
from app.models.models import DiscrepancyCategory


# ── Helper fixtures ────────────────────────────────────────────────────────────

def make_rules(**kwargs) -> dict:
    defaults = dict(
        match_fields=["reference_id"],
        strategy="exact",
        amount_tolerance=None,
        date_tolerance_days=0,
        case_sensitive=False,
        null_handling="exclude",
        amount_field="amount",
        date_field="transaction_date",
        normalization_config={},
    )
    defaults.update(kwargs)
    return defaults


# ── Normalization tests ────────────────────────────────────────────────────────

class TestNormalization:
    def test_normalize_string_lowercase(self):
        assert normalize_string("  HELLO  ") == "hello"

    def test_normalize_string_case_sensitive(self):
        assert normalize_string("HELLO", case_sensitive=True) == "HELLO"

    def test_normalize_string_none(self):
        assert normalize_string(None) is None

    def test_normalize_string_empty(self):
        assert normalize_string("   ") is None

    def test_parse_decimal_integer(self):
        assert parse_decimal("150000") == Decimal("150000")

    def test_parse_decimal_with_comma(self):
        assert parse_decimal("1,500,000.50") == Decimal("1500000.50")

    def test_parse_decimal_currency_symbol(self):
        assert parse_decimal("IDR 150000") == Decimal("150000")

    def test_parse_decimal_none(self):
        assert parse_decimal(None) is None

    def test_parse_decimal_invalid(self):
        assert parse_decimal("not-a-number") is None

    def test_parse_date_iso(self):
        d = parse_date("2026-10-27")
        assert d is not None
        assert str(d) == "2026-10-27"

    def test_parse_date_dmy(self):
        d = parse_date("27/10/2026")
        assert d is not None
        assert str(d) == "2026-10-27"

    def test_parse_date_invalid(self):
        assert parse_date("not-a-date") is None

    def test_normalize_row_strip_whitespace(self):
        row = {"name": "  hello  ", "amount": " 100 "}
        result = normalize_row(row, {"strip_whitespace": True})
        assert result["name"] == "hello"
        assert result["amount"] == "100"

    def test_normalize_row_empty_to_null(self):
        row = {"name": "", "amount": "100"}
        result = normalize_row(row, {"empty_to_null": True})
        assert result["name"] is None

    def test_idempotent_normalization(self):
        """Normalizing twice must equal normalizing once."""
        row = {"name": "  HELLO  ", "amount": " 100 "}
        config = {"strip_whitespace": True, "lowercase_strings": True, "empty_to_null": True}
        once = normalize_row(row, config)
        twice = normalize_row(once, config)
        assert once == twice


# ── Engine: exact matching ─────────────────────────────────────────────────────

class TestExactMatching:
    def test_single_exact_match(self):
        a = [{"reference_id": "TXN-001", "amount": "100000"}]
        b = [{"reference_id": "TXN-001", "amount": "100000"}]
        results = run_reconciliation(a, b, make_rules())
        assert len(results) == 1
        assert results[0].category == DiscrepancyCategory.matched

    def test_missing_in_b(self):
        a = [{"reference_id": "TXN-001"}]
        b = []
        results = run_reconciliation(a, b, make_rules())
        assert len(results) == 1
        assert results[0].category == DiscrepancyCategory.missing_in_b

    def test_missing_in_a(self):
        a = []
        b = [{"reference_id": "TXN-001"}]
        results = run_reconciliation(a, b, make_rules())
        assert len(results) == 1
        assert results[0].category == DiscrepancyCategory.missing_in_a

    def test_both_missing(self):
        a = [{"reference_id": "TXN-001"}]
        b = [{"reference_id": "TXN-002"}]
        results = run_reconciliation(a, b, make_rules())
        categories = {r.category for r in results}
        assert DiscrepancyCategory.missing_in_b in categories
        assert DiscrepancyCategory.missing_in_a in categories

    def test_multiple_exact_matches(self):
        a = [{"reference_id": f"TXN-{i:03d}", "amount": str(i * 1000)} for i in range(1, 6)]
        b = [{"reference_id": f"TXN-{i:03d}", "amount": str(i * 1000)} for i in range(1, 6)]
        results = run_reconciliation(a, b, make_rules())
        matched = [r for r in results if r.category == DiscrepancyCategory.matched]
        assert len(matched) == 5

    def test_case_insensitive_match(self):
        a = [{"reference_id": "TXN-001"}]
        b = [{"reference_id": "txn-001"}]
        results = run_reconciliation(a, b, make_rules(case_sensitive=False))
        assert results[0].category == DiscrepancyCategory.matched

    def test_case_sensitive_no_match(self):
        a = [{"reference_id": "TXN-001"}]
        b = [{"reference_id": "txn-001"}]
        results = run_reconciliation(a, b, make_rules(case_sensitive=True))
        categories = {r.category for r in results}
        assert DiscrepancyCategory.matched not in categories


# ── Engine: one-to-one constraint ─────────────────────────────────────────────

class TestOneToOne:
    def test_duplicate_in_b_causes_ambiguity(self):
        """A with one record, B with two records having the same key → ambiguous."""
        a = [{"reference_id": "TXN-001"}]
        b = [{"reference_id": "TXN-001"}, {"reference_id": "TXN-001"}]
        results = run_reconciliation(a, b, make_rules())
        # The A record should be ambiguous, not matched
        a_results = [r for r in results if r.row_a_idx == 0]
        assert len(a_results) == 1
        assert a_results[0].category == DiscrepancyCategory.ambiguous_match

    def test_matched_row_not_reused(self):
        """Once row in B is matched, it cannot be matched again."""
        a = [{"reference_id": "TXN-001"}, {"reference_id": "TXN-001"}]
        b = [{"reference_id": "TXN-001"}]
        results = run_reconciliation(a, b, make_rules())
        matched = [r for r in results if r.category == DiscrepancyCategory.matched]
        # Only one can be matched; second A row must be ambiguous or missing
        assert len(matched) <= 1


# ── Engine: amount mismatch ────────────────────────────────────────────────────

class TestAmountMismatch:
    def test_amount_mismatch_detected(self):
        a = [{"reference_id": "TXN-001", "amount": "150000"}]
        b = [{"reference_id": "TXN-001", "amount": "145000"}]
        results = run_reconciliation(a, b, make_rules())
        assert results[0].category == DiscrepancyCategory.amount_mismatch
        assert "amount" in results[0].diff_fields

    def test_amount_within_tolerance_matches(self):
        a = [{"reference_id": "TXN-001", "amount": "150000"}]
        b = [{"reference_id": "TXN-001", "amount": "150000.05"}]
        results = run_reconciliation(a, b, make_rules(amount_tolerance="1"))
        assert results[0].category == DiscrepancyCategory.matched

    def test_amount_outside_tolerance_mismatches(self):
        a = [{"reference_id": "TXN-001", "amount": "150000"}]
        b = [{"reference_id": "TXN-001", "amount": "149000"}]
        results = run_reconciliation(a, b, make_rules(amount_tolerance="500"))
        assert results[0].category == DiscrepancyCategory.amount_mismatch

    def test_decimal_precision(self):
        """Must use Decimal arithmetic, not float."""
        a = [{"reference_id": "TXN-001", "amount": "0.1"}]
        b = [{"reference_id": "TXN-001", "amount": "0.2"}]
        results = run_reconciliation(a, b, make_rules())
        diff_a = parse_decimal("0.1")
        diff_b = parse_decimal("0.2")
        assert diff_b - diff_a == Decimal("0.1")  # not 0.09999999... (float issue)
        assert results[0].category == DiscrepancyCategory.amount_mismatch


# ── Engine: date mismatch ──────────────────────────────────────────────────────

class TestDateMismatch:
    def test_date_mismatch_detected(self):
        a = [{"reference_id": "TXN-001", "transaction_date": "2026-10-01"}]
        b = [{"reference_id": "TXN-001", "transaction_date": "2026-10-05"}]
        results = run_reconciliation(a, b, make_rules())
        assert results[0].category == DiscrepancyCategory.date_mismatch

    def test_date_within_tolerance_matches(self):
        a = [{"reference_id": "TXN-001", "transaction_date": "2026-10-01"}]
        b = [{"reference_id": "TXN-001", "transaction_date": "2026-10-02"}]
        results = run_reconciliation(a, b, make_rules(date_tolerance_days=1))
        assert results[0].category == DiscrepancyCategory.matched

    def test_date_outside_tolerance_mismatches(self):
        a = [{"reference_id": "TXN-001", "transaction_date": "2026-10-01"}]
        b = [{"reference_id": "TXN-001", "transaction_date": "2026-10-03"}]
        results = run_reconciliation(a, b, make_rules(date_tolerance_days=1))
        assert results[0].category == DiscrepancyCategory.date_mismatch


# ── Engine: composite key matching ────────────────────────────────────────────

class TestCompositeKey:
    def test_composite_key_match(self):
        rules = make_rules(match_fields=["transaction_date", "amount", "currency"])
        a = [{"transaction_date": "2026-10-01", "amount": "100000", "currency": "IDR"}]
        b = [{"transaction_date": "2026-10-01", "amount": "100000", "currency": "IDR"}]
        results = run_reconciliation(a, b, rules)
        assert results[0].category == DiscrepancyCategory.matched

    def test_composite_partial_match_fails(self):
        rules = make_rules(match_fields=["transaction_date", "amount"])
        a = [{"transaction_date": "2026-10-01", "amount": "100000"}]
        b = [{"transaction_date": "2026-10-02", "amount": "100000"}]
        results = run_reconciliation(a, b, rules)
        assert results[0].category != DiscrepancyCategory.matched


# ── Engine: null handling ──────────────────────────────────────────────────────

class TestNullHandling:
    def test_null_match_field_marks_invalid(self):
        a = [{"reference_id": None}]
        b = [{"reference_id": "TXN-001"}]
        results = run_reconciliation(a, b, make_rules())
        assert any(r.category == DiscrepancyCategory.invalid_record for r in results)


# ── Engine: explanation ────────────────────────────────────────────────────────

class TestExplanations:
    def test_matched_has_explanation(self):
        a = [{"reference_id": "TXN-001"}]
        b = [{"reference_id": "TXN-001"}]
        results = run_reconciliation(a, b, make_rules())
        assert results[0].explanation
        assert len(results[0].explanation) > 0

    def test_mismatch_explanation_contains_diff(self):
        a = [{"reference_id": "TXN-001", "amount": "100"}]
        b = [{"reference_id": "TXN-001", "amount": "200"}]
        results = run_reconciliation(a, b, make_rules())
        assert results[0].explanation
        assert "100" in results[0].explanation or "200" in results[0].explanation or "amount" in results[0].explanation.lower()

    def test_missing_in_b_has_explanation(self):
        a = [{"reference_id": "TXN-999"}]
        b = []
        results = run_reconciliation(a, b, make_rules())
        assert results[0].explanation
        assert "B" in results[0].explanation or "b" in results[0].explanation.lower()


# ── Engine: determinism ────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        a = [{"reference_id": f"TXN-{i:03d}", "amount": str(i * 100)} for i in range(20)]
        b = [{"reference_id": f"TXN-{i:03d}", "amount": str(i * 100)} for i in range(20)]
        rules = make_rules()
        r1 = run_reconciliation(a, b, rules)
        r2 = run_reconciliation(a, b, rules)
        assert [r.category for r in r1] == [r.category for r in r2]

    def test_unrelated_extra_rows_do_not_affect_confirmed_matches(self):
        """Adding unrelated rows must not change already-matched pairs."""
        base_a = [{"reference_id": "TXN-001", "amount": "100"}]
        base_b = [{"reference_id": "TXN-001", "amount": "100"}]
        extra_a = [{"reference_id": "TXN-999", "amount": "999"}]

        r1 = run_reconciliation(base_a, base_b, make_rules())
        r2 = run_reconciliation(base_a + extra_a, base_b, make_rules())

        # TXN-001 match status must be the same
        match1 = next(r for r in r1 if r.data_a and r.data_a.get("reference_id") == "TXN-001")
        match2 = next(r for r in r2 if r.data_a and r.data_a.get("reference_id") == "TXN-001")
        assert match1.category == match2.category
