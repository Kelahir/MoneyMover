"""Contains MoneyMover class, the main user interface with the script"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from .ing_parser import IngParser
from .moneylover_api import MoneyLoverClient
from .prompts import CategorySelector, UserPrompts

ui = UserPrompts()


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
    ) -> None:
        script_dir = Path(__file__).resolve().parent
        self._presets_path = script_dir / "resources" / presets_fname
        self.transaction_presets = self._load_presets(self._presets_path)
        self.ml_api = MoneyLoverClient(email, password)
        self._validate_presets()
        self.bank_statement = IngParser(bank_statement_folder)
        self.ml_transactions: pd.DataFrame
        self.active_wallet: pd.Series
        self.active_wallet_name: str
        self.active_wallet_id: str
        self.wallet_categories: pd.DataFrame

    def set_wallet(self) -> None:
        """Choose an active MoneyLover wallet for your next actions."""
        self.active_wallet = ui.choose_wallet(self.wallets)
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

    def print_bank_report(self) -> None:
        """Prints transactions highlighting added and recongnized entries"""
        self.request_transactions(self.bank_statement.date_range)
        df = self.bank_statement.transactions

        df = self._check_if_already_added(df)
        df = self._compare_to_presets(df)

        ui.print_report(df)

    def print_user_presets(self) -> None:
        """Prints user presets from the json file"""
        df = self._load_presets_into_df()

        print(df)

    def display_categories(
        self, transaction_type: Literal["expense", "income"]
    ) -> None:
        """Shows categories for the selected wallet"""

        transaction_mask = self.wallet_categories["type"] == transaction_type
        wallet_categories = self.wallet_categories[transaction_mask]
        CategorySelector(wallet_categories).run()

    def transfer_bank_transactions(self) -> pd.DataFrame:
        """Transfers transactions from the latest ing bank statement to the
        MoneyLover wallet based on a predefined template. If the transaction is
        already added it is skipped (checked by transaction amount).

        Parameters
        ----------
        wallet_name : str
            Name of the target wallet in the MoneyLover

        Returns
        -------
        pd.DataFrame
            Transactions which were not transferred from the file and require
            manual entry.
        """
        self.request_transactions(self.bank_statement.date_range)
        tr_df = self.bank_statement.transactions
        tr_df = self._check_if_already_added(tr_df)
        tr_df = self._compare_to_presets(tr_df)

        transactions_to_add = tr_df[~tr_df["is_in_ml"] & tr_df["has_preset"]]

        if ui.prompt_adding(transactions_to_add):
            self._transfer_from_presets(transactions_to_add)

        remaining = tr_df[~(tr_df["is_in_ml"] | tr_df["has_preset"])]

        if ui.promt_manual_entry(remaining):
            for idx, transaction in remaining.iterrows():
                self._fill_manually(idx, transaction)

        return remaining

    def _check_if_already_added(
        self, bank_transactions: pd.DataFrame
    ) -> pd.DataFrame:
        """Compares transactions in the wallet and bank statement.

        The comparison is done by date and value. If they match, they are
        considered already added.

        Parameters
        ----------
        bank_transactions : DataFrame
            Table with bank transactions

        Returns
        -------
        DataFrame
            Same table with boolean column "is_in_ml". True if exists in ML.
        """

        if self.ml_transactions.empty:
            bank_transactions["is_in_ml"] = False
            return bank_transactions

        is_same_amount = bank_transactions["amount"].isin(
            self.ml_transactions["amount"]
        )
        is_same_date = bank_transactions["date"].isin(
            self.ml_transactions["date"]
        )

        is_in_ml = is_same_amount & is_same_date

        bank_transactions["is_in_ml"] = is_in_ml

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

    def _transfer_from_presets(self, transactions_df: pd.DataFrame) -> None:
        """Populates a MoneLover wallet with transactions from the Dataframe.

        Uses a dictionary presets to assign categories and notes to
        popular and known expenses/incomes.

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
            if not re.match(substring, transaction_value, re.IGNORECASE):
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
        try:
            category = bank_transaction["category_name"]
            category_id = self._get_category_id(
                category_name=category,
                category_type=bank_transaction["type"],
            )
        except KeyError as e:
            print(f"{category} is not a valid name for the category")
            raise KeyError(e) from e

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

    def _fill_manually(self, id_num: int, bank_transaction: pd.Series):
        """Provides CLI for manually entering the transactions"""
        # categories_df = self.ml_api.categories
        categories_df = self.wallet_categories

        transaction_type = ui.choose_transaction_type(id_num, bank_transaction)
        if transaction_type is None:
            return
        transaction_mask = categories_df["type"] == transaction_type
        # & (categories_df["wallet_id"] == self.active_wallet_id)
        # wallet_categories = categories_df[transaction_mask]
        applicable_categories = categories_df[transaction_mask]
        category = ui.choose_category(applicable_categories)

        if category is None:
            return

        category_id = self._get_category_id(
            category,
            transaction_type,
        )

        note = input("Write a transaction note: ")
        payload = self._create_payload(category_id, bank_transaction, note)
        self.ml_api.add_transaction(**payload)
        print("Transaction added\n")

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

    def _load_presets_into_df(self) -> pd.DataFrame:
        """Loads preset file into a multiindex dataframe"""
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
        df = self._load_presets_into_df()

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
