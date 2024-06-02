"""Basic tests for the moneylover api"""

# pylint: disable=W0212

import os
from datetime import datetime, timedelta

import pytest
from dotenv import load_dotenv

from money_mover.moneylover_api import MoneyLoverClient

load_dotenv()


@pytest.fixture(name="ml_client")
def fixture_ml_client():
    """Get a class instance for the tests"""
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    return MoneyLoverClient(email, password)


def test__is_token_valid(ml_client, tmp_path):
    """Token validation check"""
    # Create a temporary access token file
    access_token_file = tmp_path / "access_token.txt"
    access_token_file.write_text("test_token")

    ml_client.access_token_file = access_token_file

    # Test with token modified 4 days ago
    creation_time = (datetime.now() - timedelta(days=30)).timestamp()
    modification_time = (datetime.now() - timedelta(days=4)).timestamp()
    access_token_file.touch()
    access_token_file.write_text("test_token")
    os.utime(access_token_file, (creation_time, modification_time))
    assert ml_client._is_token_valid()

    # Test with token modified 6 days ago
    modification_time = (datetime.now() - timedelta(days=6)).timestamp()
    access_token_file.touch()
    access_token_file.write_text("test_token")
    os.utime(access_token_file, (creation_time, modification_time))
    assert not ml_client._is_token_valid()


def test__load_access_token(ml_client, tmp_path):
    """Reading token file"""
    # Create a temporary access token file
    access_token_file = tmp_path / "access_token.txt"
    access_token_file.write_text("test_token")

    ml_client.access_token_file = access_token_file

    # Test loading access token from file
    assert ml_client._load_access_token() == "test_token"

    # Test when access token file does not exist
    access_token_file.unlink()
    assert ml_client._load_access_token() is None


def test__save_access_token(ml_client, tmp_path):
    """Saving token string to a file"""
    # Create a temporary access token file
    access_token_file = tmp_path / "access_token.txt"

    ml_client.access_token_file = access_token_file
    ml_client._save_access_token("test_token")

    # Check if access token is saved correctly
    assert access_token_file.read_text() == "test_token"


def test__get_token(ml_client):
    """Getting token string from the server"""
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    assert isinstance(ml_client._get_token(email, password), str)


def test_get_user_info(ml_client):
    """Check user info retrieved"""

    user_info = ml_client.get_user_info()
    assert all(
        key in user_info
        for key in [
            "_id",
            "email",
            "client_setting",
            "subscribeProduct",
            "tags",
            "icon_package",
            "limitDevice",
            "purchased",
            "deviceId",
        ]
    )


def test_get_wallets(ml_client):
    """Check wallet info"""
    wallets = ml_client.get_wallets()

    assert len(wallets) != 0
    assert all(
        key in wallets[0]
        for key in [
            "_id",
            "name",
            "currency_id",
            "owner",
            "sortIndex",
            "transaction_notification",
            "archived",
            "account_type",
            "exclude_total",
            "icon",
            "listUser",
            "createdAt",
            "updateAt",
            "isDelete",
            "balance",
        ]
    )


def test_get_wallets_summary(ml_client):
    """Check summary entries"""
    wallets_summary = ml_client.get_wallets_summary()
    assert not wallets_summary.empty
    assert all(
        key in wallets_summary
        for key in [
            "_id",
            "name",
            "balance",
            "currency",
        ]
    )


def test_load_categories(ml_client):
    """Check category retrieval"""
    ml_client.load_categories(True)
    assert ml_client.categories_file.exists()

    assert all(
        key in ml_client.categories
        for key in [
            "wallet_id",
            "wallet_name",
            "type",
            "name",
            "_id",
            "parent",
        ]
    )
