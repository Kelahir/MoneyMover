"""Interactive terminal layer on top of MoneyMover.

MoneyMover now has two consumers - a terminal/notebook workflow and the web
app - so it only exposes the pure, prompt-free API. This module wraps a
MoneyMover instance with the prompting/printing/interactive-selection glue
(from prompts.py) needed to drive it from a terminal.
"""

from typing import Literal

import pandas as pd

from .moneymover import MoneyMover
from .prompts import CategorySelector, UserPrompts

ui = UserPrompts()


class MoneyMoverCLI:
    """Interactive terminal wrapper around a MoneyMover instance.

    Parameters
    ----------
    mover : MoneyMover
        The MoneyMover instance to drive interactively.
    """

    def __init__(self, mover: MoneyMover) -> None:
        self.mover = mover

    def set_wallet(self) -> None:
        """Choose an active MoneyLover wallet for your next actions."""
        wallet = ui.choose_wallet(self.mover.wallets)
        self.mover.select_wallet(wallet["_id"])

    def print_bank_report(self) -> None:
        """Prints transactions highlighting added and recongnized entries"""
        ui.print_report(self.mover.get_bank_report())

    def print_user_presets(self) -> None:
        """Prints user presets from the json file"""
        print(self.mover.load_presets_into_df())

    def display_categories(
        self, transaction_type: Literal["expense", "income"]
    ) -> None:
        """Shows categories for the selected wallet"""
        transaction_mask = self.mover.wallet_categories["type"] == transaction_type
        wallet_categories = self.mover.wallet_categories[transaction_mask]
        CategorySelector(wallet_categories).run()

    def transfer_bank_transactions(self) -> pd.DataFrame:
        """Transfers transactions from the latest ing bank statement to the
        MoneyLover wallet based on a predefined template. If the transaction is
        already added it is skipped (checked by transaction amount).

        Returns
        -------
        pd.DataFrame
            Transactions which were not transferred from the file and require
            manual entry.
        """
        tr_df = self.mover.get_bank_report()

        transactions_to_add = tr_df[~tr_df["is_in_ml"] & tr_df["has_preset"]]

        if ui.prompt_adding(transactions_to_add):
            self.mover.transfer_from_presets(transactions_to_add)

        remaining = tr_df[~(tr_df["is_in_ml"] | tr_df["has_preset"])]

        if ui.promt_manual_entry(remaining):
            for idx, transaction in remaining.iterrows():
                self._fill_manually(idx, transaction)

        return remaining

    def _fill_manually(self, id_num: int, bank_transaction: pd.Series) -> None:
        """Provides CLI for manually entering the transactions"""
        categories_df = self.mover.wallet_categories

        transaction_type = ui.choose_transaction_type(id_num, bank_transaction)
        if transaction_type is None:
            return

        transaction_mask = categories_df["type"] == transaction_type
        applicable_categories = categories_df[transaction_mask]
        category = ui.choose_category(applicable_categories)

        if category is None:
            return

        note = input("Write a transaction note: ")
        self.mover.add_manual_transaction(
            amount=bank_transaction["amount"],
            date=bank_transaction["date"],
            category_name=category,
            transaction_type=transaction_type,
            note=note,
        )
        print("Transaction added\n")
