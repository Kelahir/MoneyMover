"""Basic tests for the ING parser"""

# pylint: disable=W0212

import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from money_mover.ing_parser import COLUMNS, IngParser


@pytest.fixture(name="ing_parser")
def fixture_ing_parser():
    """Fixture a parcer with dummy file"""
    return IngParser(statement_folder="./tests")


def test_find_file(ing_parser):
    """Test file search in the folder"""
    ing_parser._find_file()
    assert ing_parser._recent_bank_statement.exists()


def test_find_closest_end_date_file(ing_parser):
    """Test when there are multiple files with different dates"""
    files = [
        "NL55INGB0000000000_01-01-2024_31-01-2024.csv",
        "NL55INGB0000000000_01-02-2024_29-02-2024.csv",
        "NL55INGB0000000000_01-03-2024_30-03-2024.csv",
        "NL55INGB0000000000_01-12-2023_31-12-2023.csv",
        "NL55INGB0000000000_01-11-2023_30-11-2023.csv",
    ]

    file_pattern = r"(.+)_(\d{2}-\d{2}-\d{4})_(\d{2}-\d{2}-\d{4})"
    file_matches = [re.match(file_pattern, file) for file in files]

    recent_file = ing_parser._find_closest_end_date_file(file_matches)
    assert recent_file == "NL55INGB0000000000_01-03-2024_30-03-2024.csv"


def test_parse_csv(ing_parser):
    """Test that the values are parsed as expected"""
    ing_parser._find_file()
    df = ing_parser._parse_csv()

    # Check if DataFrame is not empty
    assert not df.empty

    # Check if all columns are present
    assert set(df.columns) == set(COLUMNS)

    # Check if 'date' column is datetime type
    assert isinstance(df["date"].iloc[0], pd.Timestamp)

    # Check if 'amount' column is float64 type
    assert isinstance(df["amount"].iloc[0], float)


def test_init(ing_parser):
    """Testing initialised values"""
    # Check if transactions attribute is set
    assert isinstance(ing_parser.transactions, pd.DataFrame)

    # Check if date_range attribute is set
    assert isinstance(ing_parser.date_range, tuple)
    assert isinstance(ing_parser.date_range[0], datetime)
    assert isinstance(ing_parser.date_range[1], datetime)

    # Check if _recent_bank_statement attribute is set
    assert isinstance(ing_parser._recent_bank_statement, Path)
