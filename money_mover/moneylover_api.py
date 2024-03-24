"""
Moneylover API client to communicate with the server, send and retrieve data.

The client requires logging-in to acquire a token, which then can be reused
foe 5-7 days before expiration.

Wallet categories are cached for quicker access.
"""

import getpass
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests


class MoneyLoverClient:
    """MoneyLover api client. Log in using MoneyLover account credentials.

    On instance creation it logs in, saves the
    access token, retrieves existing wallets and expense categories.

    Parameters
    ----------
    email : str, optional
        MoneyLover account email, by default None
    password : str, optional
        MoneyLover account password, by default None

    Attributes
    ----------
    wallets : DataFrame
        Table with wallets

    categories : DataFrame
        Table with categories for every wallet

    Public methods
    --------------
    get_user_info()
        Information about the logged in user and settings

    get_wallets()
        Existing wallets and their full information

    get_wallets_summary()
        Balance and currency for every existing wallet

    load_categories()
        Updates a file with transaction categories and wallets

    get_transactions()
        Returns records in a wallet between two dates

    add_transaction()
        Adds a new record to a wallet
    """

    api_url = "https://web.moneylover.me/api"
    script_dir = Path(__file__).resolve().parent
    access_token_file = script_dir / "resources/access_token.txt"
    categories_file = script_dir / "resources/categories.csv"

    def __init__(self, email: str | None = None, password: str | None = None):
        self.wallets: pd.DataFrame
        self.categories: pd.DataFrame

        access_token = self._load_access_token()

        if access_token is None:
            print("MoneyLover login required")
            if email is None:
                email = input("E-mail: ")
            if password is None:
                password = getpass.getpass("Password: ")

            access_token = self._get_token(email, password)
            self._save_access_token(access_token)

        self._jwt_token = access_token

        self.get_wallets_summary()
        self.load_categories()

    def _load_access_token(self):
        """Try to load the access token from the file"""
        try:
            if self._is_token_valid():
                with open(
                    self.access_token_file, "r", encoding="utf_8"
                ) as file:
                    return file.read().strip()
            else:
                return None

        except FileNotFoundError:
            return None

    def _is_token_valid(self, days=5) -> bool:
        """Check if the saved token has expired or not.

        Parameters
        ----------
        days : int, optional
            Expiration target in days, by default 5

        Returns
        -------
        bool
            True if the file is older than days passed in the argument.
        """
        file_modified_time = os.path.getmtime(self.access_token_file)
        file_modified_datetime = datetime.fromtimestamp(file_modified_time)
        time_passed = datetime.now() - file_modified_datetime

        return time_passed < timedelta(days=days)

    def _save_access_token(self, token):
        """Save the token to the file"""
        with open(self.access_token_file, "w", encoding="utf_8") as file:
            file.write(token)

    def _get_token(self, email: str, password: str) -> str:
        """Make a POST request to the 'login-url' endpoint to obtain the
        access token.

        Parameters
        ----------
        email : str
            MoneyLover account email
        password : str
            MoneyLover account password

        Returns
        -------
        str
            Access token used for authentification
        """
        login_url_response = requests.post(
            "https://web.moneylover.me/api/user/login-url", timeout=5
        )
        login_url_data = login_url_response.json()

        request_token = login_url_data["data"]["request_token"]
        client_id = (
            login_url_data["data"]["login_url"]
            .split("client=")[1]
            .split("&")[0]
        )

        print("Request token and client id received")
        print("Logging in...")

        # POST request to the 'token' endpoint to obtain the access token
        token_url = "https://oauth.moneylover.me/token"
        headers = {
            "Authorization": f"Bearer {request_token}",
            "client": client_id,
        }
        data = {"email": email, "password": password}

        token_response = requests.post(
            token_url, headers=headers, data=data, timeout=5
        )
        token_data = token_response.json()

        access_token = token_data["access_token"]

        print("Logged in successfully. Access token received.")

        return access_token

    def _post_request(
        self,
        path: str,
        headers: dict | None = None,
        body: dict | None = None,
        data: dict | None = None,
    ) -> dict | list[dict]:
        """Assembles and sends a post request to the Moneylover API.

        Parameters
        ----------
        path : str
            Added path for an API url
        headers : dict, optional
            Additional request headers, by default None
        body : dict, optional
            Request payload, by default None
        data : dict, optional
            Payload as data, used to get categories, by default None

        Returns
        -------
        dict
            Moneylover API response as json dict or list of dicts
        """
        url = self.api_url + path
        headers = {
            "authorization": f"AuthJWT {self._jwt_token}",
            **(headers or {}),
        }

        response = requests.post(
            url, headers=headers, data=data, json=body, timeout=120
        )
        response.raise_for_status()

        response_data = response.json()

        if "error" in response_data and response_data["error"] != 0:
            error_msg = (
                f'Error {response_data["error"]}, {response_data["msg"]}'
            )
            raise MoneyLoverException(error_msg)

        if "e" in response_data:
            error_msg = f'Error {response_data["e"]}, {response_data["msg"]}'
            raise MoneyLoverException(error_msg)

        return response_data["data"]

    def get_user_info(self) -> dict:
        """Returns user info: id, email, settings, subscription and so on."""
        user_info = self._post_request("/user/info")
        if isinstance(user_info, dict):
            return user_info

        raise ReturnedTypeError()

    def get_wallets(self) -> list[dict]:
        """Returns a list of wallets. Each wallet has keys such as: _id, name,
        currency_id, owner, listUser, createdAt, updateAt, balance and more.

        Returns
        -------
        list[dict]
            List of dictionaries with info about each wallet
        """
        wallets = self._post_request("/wallet/list")
        if isinstance(wallets, list):
            return wallets

        raise ReturnedTypeError()

    def get_wallets_summary(self) -> pd.DataFrame:
        """Retrieves wallets data and returns only the most relevant
        information: _id, name, balance and currency of each wallet.

        Returns
        -------
        pd.DataFrame
            Dataframe with wallets info. Cols:  _id, name, balance, currency
        """
        wallets = self.get_wallets()
        wallet_names = []

        for wallet in wallets:
            wallet_data = {
                "_id": wallet["_id"],
                "name": wallet["name"],
                "balance": list(wallet["balance"][0].values())[0],
                "currency": list(wallet["balance"][0].keys())[0],
            }

            wallet_names.append(wallet_data)
        self.wallets = pd.DataFrame(wallet_names)

        return self.wallets

    def load_categories(self, reload: bool = False) -> None:
        """There are a lot of categories and it takes time to load them.
        So this method retrives them once and saves them to a file.

        Parameters
        ----------
        reload : bool, optional
            Pass a True to forcefully update the categories, by default False
        """
        types = {0: "debt/loan", 1: "income", 2: "expense"}

        if self.categories_file.exists() and not reload:
            self.categories = pd.read_csv(self.categories_file)
        else:
            all_categories = pd.DataFrame()
            for _, wallet in self.wallets.iterrows():
                wallet_categories = pd.DataFrame(
                    self._get_wallet_categories(wallet["_id"])
                )
                wallet_categories["wallet_id"] = wallet["_id"]
                wallet_categories["wallet_name"] = wallet["name"]

                # replace numeric type with a string
                wallet_categories.replace({"type": types}, inplace=True)

                all_categories = pd.concat([all_categories, wallet_categories])

            self.categories = all_categories[
                ["wallet_id", "wallet_name", "type", "name", "_id", "parent"]
            ]
            self.categories.to_csv(self.categories_file)

    def _get_wallet_categories(self, wallet_id: str) -> list[dict]:
        """Retrieves wallet expense and income categories.

        Parameters
        ----------
        wallet_id : str
            Wallet _id as a string

        Returns
        -------
        list[dict]
            List of available categories for a wallet with _id, name, etc.
        """
        categories = self._post_request(
            path="/category/list",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"walletId": wallet_id},
        )
        if isinstance(categories, list):
            return categories

        raise ReturnedTypeError()

    def get_transactions(
        self,
        wallet_id: str,
        start_date: str | datetime,
        end_date: str | datetime,
    ) -> dict:
        """Returns transaction info for the wallet between two dates.

        Parameters
        ----------
        wallet_id : str
            Wallet unique _id number
        start_date : str | datetime
            Start date of the range as datetime or "dd.mm.yyyy"
        end_date : str | datetime
            End date of the range as datetime or "dd.mm.yyyy"

        Returns
        -------
        dict
            Transactions in the wallet for the requested range
        """
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%d.%m.%Y")
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%d.%m.%Y")

        transactions = self._post_request(
            path="/transaction/list",
            body={
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "walletId": wallet_id,
            },
        )
        if isinstance(transactions, dict):
            return transactions

        raise ReturnedTypeError()

    def add_transaction(
        self,
        wallet_id: str,
        category_id: str,
        amount: float,
        note: str,
        date: str | datetime,
    ) -> dict:
        """Adds an income or an expense record to the wallet

        Parameters
        ----------
        wallet_id : str
            Wallet unique _id
        category_id : str
            Expense or income category _id
        amount : float
            Transaction amount
        note : str
            Note for the transaction
        date : str | datetime
            Date of the transaction as datetime or "dd.mm.yyyy" string

        Returns
        -------
        dict
            Sends a post request. Returns a transaction data.
        """
        if isinstance(date, str):
            date = datetime.strptime(date, "%d.%m.%Y")

        transaction_data = {
            "with": [],  # You can customize this if needed
            "account": wallet_id,
            "category": category_id,
            "amount": amount,
            "note": note,
            "displayDate": date.strftime("%Y-%m-%d"),
        }

        response = self._post_request(
            path="/transaction/add",
            headers={"Content-Type": "application/json"},
            body=transaction_data,
        )
        if isinstance(response, dict):
            return response

        raise ReturnedTypeError()


class ReturnedTypeError(Exception):
    """Used to check the data type returned by MoneyLover API."""

    def __init__(
        self, message="MoneyLover API returned an unexpected data type"
    ):
        self.message = message
        super().__init__(self.message)


class MoneyLoverException(Exception):
    """Used for the MoneyLover API errors."""

    def __init__(self, message="MoneyLover API returned an error"):
        self.message = message
        super().__init__(self.message)
