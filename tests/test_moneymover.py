"""Tests for the pure logic in MoneyMover - no login, no network calls.

Builds MoneyMover instances via `__new__`, bypassing `__init__` (which logs
in for real), so these run fast and offline. Only attributes a given test
actually needs are set by hand.

Deliberately NOT covered here: _get_category_id, select_wallet's category
filtering, add_manual_transaction, transfer_from_presets,
insert_recognized_transactions, get_bank_report. All of these depend on the
current wallet-scoped category structure, which is being restructured (see
.claude/review_notes.md) - tests written against it now would just need
rewriting once that lands.
"""

# pylint: disable=W0212

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from money_mover.moneymover import MoneyMover

PRESETS_PATH = (
    Path(__file__).resolve().parent.parent
    / "money_mover"
    / "resources"
    / "example_presets.json"
)


@pytest.fixture(name="mover")
def fixture_mover():
    """A MoneyMover instance built without logging in or touching the network."""
    mover = MoneyMover.__new__(MoneyMover)
    mover._presets_path = PRESETS_PATH
    mover.transaction_presets = mover._load_presets(PRESETS_PATH)
    mover.ml_api = SimpleNamespace(categories=pd.DataFrame())
    mover.ml_transactions = pd.DataFrame()
    mover.active_wallet_id = "wallet-1"
    return mover


def _transaction(**overrides) -> pd.Series:
    """A bank transaction row with sensible defaults, overridable per test."""
    row = {
        "date": pd.Timestamp("2024-01-01"),
        "name": "Some shop",
        "account": "NL55INGB0000000000",
        "counterparty": "NL5500001111222233",
        "code": "GT",
        "debit/credit": "Debit",
        "amount": 10.0,
        "transaction type": "Online Banking",
        "notifications": "",
    }
    row.update(overrides)
    return pd.Series(row)


class TestIsPresetMatched:
    """_is_preset_matched: does a bank transaction satisfy a preset's conditions."""

    def test_matches_on_name_and_debit_credit(self, mover):
        preset = {
            "conditions": {"name": ".*local supermarket", "debit/credit": "Debit"},
            "label": {"note": "Jumbo groceries", "category_name": "Groceries", "type": "expense"},
        }
        transaction = _transaction(name="Your local supermarket", **{"debit/credit": "Debit"})
        assert mover._is_preset_matched(transaction, preset)

    def test_does_not_match_wrong_debit_credit(self, mover):
        preset = {
            "conditions": {"name": ".*local supermarket", "debit/credit": "Debit"},
            "label": {},
        }
        transaction = _transaction(name="Your local supermarket", **{"debit/credit": "Credit"})
        assert not mover._is_preset_matched(transaction, preset)

    def test_case_insensitive(self, mover):
        preset = {"conditions": {"name": "netflix.*"}, "label": {}}
        transaction = _transaction(name="NETFLIX INTERNATIONAL B.V.")
        assert mover._is_preset_matched(transaction, preset)

    def test_invalid_regex_does_not_raise(self, mover):
        """A malformed regex in a preset shouldn't crash matching - it should
        just fail to match that preset (and print a warning)."""
        preset = {"conditions": {"name": "("}, "label": {"category_name": "x"}}
        transaction = _transaction(name="anything")
        assert not mover._is_preset_matched(transaction, preset)


class TestCompareToPresets:
    """_compare_to_presets: tags a whole DataFrame with preset matches."""

    def test_tags_matching_row(self, mover):
        df = pd.DataFrame([_transaction(name="Your local supermarket")])
        result = mover._compare_to_presets(df)
        assert result.loc[0, "has_preset"]
        assert result.loc[0, "category_name"] == "Groceries"
        assert result.loc[0, "type"] == "expense"

    def test_leaves_unmatched_row_untagged(self, mover):
        df = pd.DataFrame([_transaction(name="Some random shop")])
        result = mover._compare_to_presets(df)
        assert not result.loc[0, "has_preset"]


class TestCheckIfAlreadyAdded:
    """_check_if_already_added: is a bank transaction already in MoneyLover."""

    def test_flags_matching_amount_and_date(self, mover):
        mover.ml_transactions = pd.DataFrame(
            [{"amount": 125.43, "date": pd.Timestamp("2024-01-01")}]
        )
        df = pd.DataFrame([_transaction(amount=125.43, date=pd.Timestamp("2024-01-01"))])
        result = mover._check_if_already_added(df)
        assert result.loc[0, "is_in_ml"]
        assert not result.loc[0, "is_possible_duplicate"]

    def test_does_not_flag_when_ml_empty(self, mover):
        mover.ml_transactions = pd.DataFrame()
        df = pd.DataFrame([_transaction()])
        result = mover._check_if_already_added(df)
        assert not result.loc[0, "is_in_ml"]
        assert not result.loc[0, "is_possible_duplicate"]

    def test_does_not_flag_unrelated_transaction(self, mover):
        mover.ml_transactions = pd.DataFrame(
            [{"amount": 50.0, "date": pd.Timestamp("2024-03-01")}]
        )
        df = pd.DataFrame([_transaction(amount=125.43, date=pd.Timestamp("2024-01-01"))])
        result = mover._check_if_already_added(df)
        assert not result.loc[0, "is_in_ml"]
        assert not result.loc[0, "is_possible_duplicate"]

    def test_amount_and_date_must_match_on_the_same_row(self, mover):
        """A match requires a single MoneyLover transaction with both this
        amount and this date - matching them independently against two
        different rows isn't enough to call it a duplicate."""
        mover.ml_transactions = pd.DataFrame(
            [
                {"amount": 125.43, "date": pd.Timestamp("2024-03-01")},
                {"amount": 50.0, "date": pd.Timestamp("2024-01-01")},
            ]
        )
        df = pd.DataFrame([_transaction(amount=125.43, date=pd.Timestamp("2024-01-01"))])
        result = mover._check_if_already_added(df)
        assert not result.loc[0, "is_in_ml"]

    def test_amount_only_match_is_a_possible_duplicate(self, mover):
        """Same amount, different date, within the already period-scoped
        ml_transactions - not a confirmed duplicate, but worth a human
        looking at it rather than being silently auto-inserted."""
        mover.ml_transactions = pd.DataFrame(
            [{"amount": 125.43, "date": pd.Timestamp("2024-01-15")}]
        )
        df = pd.DataFrame([_transaction(amount=125.43, date=pd.Timestamp("2024-01-01"))])
        result = mover._check_if_already_added(df)
        assert not result.loc[0, "is_in_ml"]
        assert result.loc[0, "is_possible_duplicate"]


class TestCreatePayload:
    """_create_payload: assembles the add_transaction keyword arguments."""

    def test_builds_expected_fields(self, mover):
        transaction = _transaction(amount=42.5, date=pd.Timestamp("2024-01-05"))
        payload = mover._create_payload("category-1", transaction, "a note")
        assert payload == {
            "wallet_id": "wallet-1",
            "category_id": "category-1",
            "amount": 42.5,
            "date": pd.Timestamp("2024-01-05"),
            "note": "a note",
        }


class TestValidatePresets:
    """_validate_presets: presets must reference real category names.

    Only checks name membership in a categories table - agnostic to whether
    that table ends up wallet-scoped or global, so safe to test now.
    """

    def test_all_valid_categories_passes(self, mover):
        mover.ml_api.categories = pd.DataFrame(
            {"name": ["Groceries", "Television", "Trains", "Salary"]}
        )
        assert mover._validate_presets() is True

    def test_missing_category_fails(self, mover):
        mover.ml_api.categories = pd.DataFrame({"name": ["Groceries"]})
        assert mover._validate_presets() is False
