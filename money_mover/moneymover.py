"""Contains MoneyMover class, the main user interface with the script"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from .ing_parser import IngParser
from .moneylover_api import MoneyLoverClient


class MoneyMover:
    """
    Manages the movement of transactions between ING bank statements and MoneyLover.

    Parameters
    ----------
    email : str, optional
        Email associated with the MoneyLover account, by default None
    password : str, optional
        Password associated with the MoneyLover account, by default None
    bank_statement_folder : str, optional
        Path to the folder containing bank statements, by default "./bank_statements/"

    Attributes
    ----------
    transaction_presets : dict
        Predefined transaction presets loaded from presets.json file
    ml_api : MoneyLoverClient
        Instance of the MoneyLoverClient used for API interactions
    bank_statement : IngParser
        Instance of the IngParser used to parse ING bank statements
    ml_transactions : pd.DataFrame
        DataFrame containing last retrieved MoneyLover transactions
    active_wallet : pd.Series
        Series containing details of the active MoneyLover wallet
    active_wallet_name : str
        Name of the active MoneyLover wallet
    active_wallet_id : str
        ID of the active MoneyLover wallet
    """

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        bank_statement_folder: str = "./bank_statements/",
        presets_fname: str = "user_presets.json",
        bank_statement: str | None = None,
    ) -> None:
        script_dir = Path(__file__).resolve().parent
        self._presets_path = script_dir / "resources" / presets_fname
        self.transaction_presets = self._load_presets(self._presets_path)
        self.ml_api = MoneyLoverClient(email, password)
        self._validate_presets()
        self._bank_statement_folder = bank_statement_folder
        self.load_bank_statement(bank_statement)
        self.ml_transactions: pd.DataFrame
        self.active_wallet: pd.Series
        self.active_wallet_name: str
        self.active_wallet_id: str
        self.wallet_categories: pd.DataFrame

    def load_bank_statement(self, bank_statement: str | None = None) -> None:
        """(Re)loads the bank statement, auto-detecting the latest file in
        the configured folder if no explicit path is given.

        Parameters
        ----------
        bank_statement : str, optional
            Path to a specific statement file, by default None (auto-detect)
        """
        self.bank_statement = IngParser(
            self._bank_statement_folder, bank_statement=bank_statement
        )

    def select_wallet(self, wallet_id: str) -> None:
        """Sets the active MoneyLover wallet by id, without a CLI prompt.

        Parameters
        ----------
        wallet_id : str
            _id of the wallet, as returned in the `.wallets` DataFrame
        """
        self.active_wallet = self.wallets[
            self.wallets["_id"] == wallet_id
        ].iloc[0]
        self.active_wallet_name = self.active_wallet["name"]
        self.active_wallet_id = self.active_wallet["_id"]

        mask = self.ml_api.categories["wallet_id"] == self.active_wallet_id
        self.wallet_categories = self.ml_api.categories[mask]

    @property
    def wallets(self) -> pd.DataFrame:
        """Returns wallet summary with id, names, balance and currency"""

        return self.ml_api.wallets

    @property
    def this_month(self) -> pd.DataFrame:
        """Returns current month entries in the selected wallet"""
        today_date = datetime.today()
        start_of_month = today_date.replace(day=1)

        self.request_transactions((start_of_month, today_date))
        return self.ml_transactions

    @property
    def previous_month(self):
        """Returns previous month entries in the selected wallet"""
        this_month = datetime.today().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        end_prev_month = this_month - timedelta(days=1)
        start_prev_month = end_prev_month.replace(day=1)

        self.request_transactions((start_prev_month, end_prev_month))
        return self.ml_transactions

    def request_transactions(
        self, date_range: tuple[datetime, datetime]
    ) -> pd.DataFrame:
        """Calls ML api to retrieve transactions for the wallet and formats them for readability"""

        start_date, end_date = date_range

        raw_transactions = self.ml_api.get_transactions(
            self.active_wallet_id,
            start_date,
            end_date,
        )
        self.ml_transactions = self._format_transactions(raw_transactions)
        return self.ml_transactions

    def get_bank_report(self) -> pd.DataFrame:
        """Compares bank statement transactions against MoneyLover records
        and presets, without any CLI interaction.

        Returns
        -------
        pd.DataFrame
            Bank transactions with "is_in_ml" and "has_preset" columns, plus
            preset-derived note/category_name/type where matched.
        """
        self.request_transactions(self.bank_statement.date_range)
        df = self.bank_statement.transactions

        df = self._check_if_already_added(df)
        df = self._compare_to_presets(df)

        return df

    def insert_recognized_transactions(self) -> pd.DataFrame:
        """Adds every preset-matched transaction not already in MoneyLover
        to the active wallet, without any CLI prompt.

        Possible duplicates are excluded even if they also match a preset -
        an ambiguous match should never be auto-inserted, since that's
        exactly the case that risks creating a real duplicate.

        Returns
        -------
        pd.DataFrame
            The rows that were inserted.
        """
        df = self.get_bank_report()
        to_add = df[
            ~df["is_in_ml"] & ~df["is_possible_duplicate"] & df["has_preset"]
        ]
        self.transfer_from_presets(to_add)
        return to_add

    def add_manual_transaction(
        self,
        amount: float,
        date: datetime,
        category_name: str,
        transaction_type: Literal["expense", "income"],
        note: str,
    ) -> dict:
        """Adds a single transaction to the active wallet, without any CLI
        prompt. Callers already know the amount/date (e.g. from a bank
        statement row) and the category/note a user picked.

        Parameters
        ----------
        amount : float
            Signed transaction amount
        date : datetime
            Transaction date
        category_name : str
            The most specific category picked - a sub-category name if one
            was chosen, otherwise the parent category name
        transaction_type : "expense" | "income"
            Used to disambiguate categories with the same name across types
        note : str
            Note to attach to the transaction

        Returns
        -------
        dict
            MoneyLover API response for the created transaction
        """
        category_id = self._get_category_id(category_name, transaction_type)
        payload = {
            "wallet_id": self.active_wallet_id,
            "category_id": category_id,
            "amount": amount,
            "date": date,
            "note": note,
        }
        return self.ml_api.add_transaction(**payload)

    def _check_if_already_added(
        self, bank_transactions: pd.DataFrame
    ) -> pd.DataFrame:
        """Compares transactions in the wallet and bank statement.

        A bank transaction is only considered already added if a single
        MoneyLover transaction matches it on both date and amount together
        ("is_in_ml"). Matching the two independently (some MoneyLover
        transaction has this amount, and some other one has this date) isn't
        enough to call it a duplicate, but it's still worth flagging for a
        human to check ("is_possible_duplicate") rather than silently
        letting an automatic insert risk creating a real duplicate.

        ml_transactions is already scoped to the bank statement's date
        range (see get_bank_report), so no extra date window is needed for
        the possible-duplicate check.

        Parameters
        ----------
        bank_transactions : DataFrame
            Table with bank transactions

        Returns
        -------
        DataFrame
            Same table with boolean columns "is_in_ml" (exact date+amount
            match) and "is_possible_duplicate" (amount matches something in
            the period, but not paired with this date - needs review).
        """

        if self.ml_transactions.empty:
            bank_transactions["is_in_ml"] = False
            bank_transactions["is_possible_duplicate"] = False
            return bank_transactions

        ml_pairs = pd.MultiIndex.from_frame(
            self.ml_transactions[["amount", "date"]]
        )
        bank_pairs = pd.MultiIndex.from_frame(
            bank_transactions[["amount", "date"]]
        )
        is_in_ml = bank_pairs.isin(ml_pairs)

        is_same_amount = bank_transactions["amount"].isin(
            self.ml_transactions["amount"]
        )

        bank_transactions["is_in_ml"] = is_in_ml
        bank_transactions["is_possible_duplicate"] = is_same_amount & ~is_in_ml

        return bank_transactions

    def _compare_to_presets(
        self, transactions_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Look for a matching preset for every bank transaction.

        Parameters
        ----------
        transactions_df : pd.DataFrame
            Dataframe with bank transactions

        Returns
        -------
        pd.DataFrame
            Bank transactions with identified presets and their info
        """
        transactions_df["has_preset"] = False
        preset_columns = ["note", "category_name", "type"]

        for idx, bank_transaction in transactions_df.iterrows():
            for preset in self.transaction_presets:
                if self._is_preset_matched(bank_transaction, preset):
                    transactions_df.at[idx, "has_preset"] = True
                    for column in preset_columns:
                        transactions_df.at[idx, column] = preset["label"][
                            column
                        ]
                    break

        return transactions_df

    def transfer_from_presets(self, transactions_df: pd.DataFrame) -> None:
        """Populates a MoneLover wallet with transactions from the Dataframe.

        Uses a dictionary presets to assign categories and notes to
        popular and known expenses/incomes. Public since it's also called
        directly by MoneyMoverCLI (which already has the bank report
        fetched and shouldn't have to trigger another fetch just to reuse
        insert_recognized_transactions()).

        Parameters
        ----------
        transactions_df : pd.DataFrame
            Dataframe with transactions to populate

        Returns
        -------
        pd.DataFrame
            Dataframe with unmatched transactions
        """
        for idx, transaction in transactions_df.iterrows():
            payload = self._create_payload_from_preset(transaction)
            self.ml_api.add_transaction(**payload)

            print(
                f"Row {idx}: {payload['note']}: ",
                f"{payload['amount']} - Added to Moneylover",
            )

    def _is_preset_matched(
        self, bank_transaction: pd.Series, preset: dict
    ) -> bool:
        """Checks if preset condition is met by the bank transaction.

        Parameters
        ----------
        bank_transaction : pd.Series
            A row with bank transaction details
        preset : dict
            Filter preset with note and category

        Returns
        -------
        bool
            True if all preset requirements are matched, False otherwise
        """
        conditions = preset["conditions"]

        for column, substring in conditions.items():
            transaction_value = str(bank_transaction.get(column, ""))
            try:
                is_match = re.match(substring, transaction_value, re.IGNORECASE)
            except re.error as e:
                print(
                    f"Invalid regex '{substring}' for column '{column}' "
                    f"in preset {preset['label']}: {e}"
                )
                return False
            if not is_match:
                return False

        return True

    def _create_payload_from_preset(self, bank_transaction: pd.Series) -> dict:
        """Creates keyword arguments for the MoneyLover add_transaction method
        based on a preset filter.

        Parameters
        ----------
        bank_transaction : pd.Series
            A row with bank transaction details
        preset : dict
            Filter preset with note and category

        Returns
        -------
        dict
            All needed kwargs for MoneLover API to add a transaction
        """
        category = bank_transaction["category_name"]

        try:
            category_id = self._get_category_id(
                category_name=category,
                category_type=bank_transaction["type"],
            )
        except ValueError:
            print(f"{category} is not a valid name for the category")
            raise

        return self._create_payload(
            category_id,
            bank_transaction,
            bank_transaction["note"],
        )

    def _create_payload(self, category_id, bank_transaction, note) -> dict:
        """Creates a payload for the moneylover API"""
        payload = {
            "wallet_id": self.active_wallet_id,
            "category_id": category_id,
            "amount": bank_transaction["amount"],
            "date": bank_transaction["date"],
            "note": note,
        }
        return payload

    def _get_category_id(self, category_name: str, category_type: str) -> str:
        """Return a corresponding category id from a cached categories file.

        Parameters
        ----------
        category_name : str
            Name of the MoneyLover category for the transaction

        Returns
        -------
        str
            Unique category _id
        """

        df = pd.read_csv(self.ml_api.categories_file)
        wallet_filter = df["wallet_id"] == self.active_wallet_id
        category_filter = df["name"] == category_name
        type_filter = df["type"] == category_type

        category_id = df[wallet_filter & category_filter & type_filter]
        if category_id.empty:
            raise ValueError(f"No matching category found for {category_name}")
        if category_id["_id"].size > 1:
            print(
                f"{category_id['_id'].size} id matches for the ",
                f"name {category_name}.",
            )
        return category_id.iloc[0]["_id"]

    def _format_transactions(self, response: dict) -> pd.DataFrame:
        """Formats the raw transactions response from MoneLover to retrieve
        the information like note, summ, date and category.

        Parameters
        ----------
        response : dict
            Raw POST response with MoneyLover transactions

        Returns
        -------
        pd.DataFrame
            Dataframe with formatted MoneyLover transactions
        """
        transactions_info = []

        for transaction in response.get("transactions", []):
            printable = {
                "note": transaction.get("note"),
                "amount": round(transaction.get("amount", 0), 2),
                "date": pd.to_datetime(
                    transaction.get("displayDate")
                ).tz_localize(None),
                "category": transaction.get("category", {}).get("name"),
            }
            transactions_info.append(printable)

        df = pd.DataFrame(transactions_info)
        return df

    def _load_presets(
        self,
        path: Path,
        keys: list[str] = None,
    ) -> dict:
        """Loads presets with known transactions from an external file

        Initially I wanted to separate expenses and incomes, but filters
        rarely overlap for me, so I combine them:"""
        if not path.exists():
            raise FileNotFoundError(
                "Preset file not found. Create a file and pass the right argument"
            )

        if keys is None:
            keys = ["expenses", "incomes"]

        with open(path, "r", encoding="utf8") as json_file:
            raw_presets = json.load(json_file)

        presets = []
        for key in keys:
            if key in raw_presets:
                presets.extend(raw_presets[key])

        return presets

    def _flatten_for_dataframe(self, json_data: dict):
        """Flattens a nested dictionary by combining keys into tuples."""
        normalized_data = [
            {
                (outer_key, inner_key): inner_val
                for outer_key, inner_dict in item.items()
                for inner_key, inner_val in inner_dict.items()
            }
            for item in json_data
        ]
        return normalized_data

    def load_presets_into_df(self) -> pd.DataFrame:
        """Loads preset file into a multiindex dataframe. Public since
        MoneyMoverCLI's print_user_presets() also needs it."""
        template = self._load_presets(self._presets_path, ["example_template"])
        preferred_order = self._flatten_for_dataframe(template)
        preferred_order = list(preferred_order[0].keys())

        normalized_data = self._flatten_for_dataframe(self.transaction_presets)

        df = pd.DataFrame(normalized_data, columns=preferred_order)

        df.columns = pd.MultiIndex.from_tuples(df.columns)

        df = df.dropna(axis=1, how="all")
        df = df.fillna("")

        return df

    def _validate_presets(self) -> bool:
        """Checks that user presets use valid categories"""
        df = self.load_presets_into_df()

        valid_mask = df["label", "category_name"].isin(
            self.ml_api.categories["name"]
        )
        if valid_mask.all():
            print("All user presets have valid categories")
            return True
        else:
            print("Invalid categories in user presets:")
            print(df.loc[~valid_mask])
            return False
