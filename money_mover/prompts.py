"""User prompts and CLI for the MoneyMover.
"""

import os

import pandas as pd

TRANSACTION_TYPES = {"d": "debt/loan", "i": "income", "e": "expense"}


class UserPrompts:
    """General class to handle command line interface prompts"""

    def __init__(self) -> None:
        pass

    def choose_wallet(self, wallets: pd.DataFrame) -> pd.Series:
        """Prompts user to choose a wallet for the session

        Parameters
        ----------
        wallets : pd.DataFrame
            Wallets as received from the MoneyLover API

        Returns
        -------
        pd.Series
            Returns a selected wallet row
        """
        print(wallets[["name", "balance", "currency"]], "\n")

        while True:
            inp = input("Select a wallet by its index: ")

            if inp.isnumeric() and (0 <= int(inp) < len(wallets)):
                wallet_id = int(inp)
                print(f"Wallet selected: {wallets.iloc[wallet_id]["name"]}\n")

                return wallets.iloc[wallet_id]
            else:
                self._invalid_input()

    def choose_transaction_type(self, idx, bank_transaction):
        """Prompt to choose a type for the transaction"""
        print("Processing:\n")
        self.print_line(idx, bank_transaction)
        print(
            "What is a transaction type?\n"
            "(e)xpense, (i)ncome or (d)ebt/loan?\n"
            "Type 's' to skip this transaction."
        )
        while True:
            user_input = input("\n>>")
            if user_input == "s":
                print("Skipping transaction")
                return None
            elif user_input in TRANSACTION_TYPES:
                transaction_type = TRANSACTION_TYPES.get(user_input)
                print(f"---selected {transaction_type}")
                return transaction_type
            else:
                self._invalid_input()
                continue

    def choose_category(self, categories: pd.DataFrame):
        """Prompts to select a transaction category"""
        selected_category = CategorySelector(categories).run()
        return selected_category

    def promt_manual_entry(self, bank_transactions: pd.DataFrame) -> bool:
        """Prompts if user wants to manually add remaining transactions.

        Parameters
        ----------
        bank_transactions : pd.DataFrame
            Remaining transactions for manual entry

        Returns
        -------
        bool
            True if user proceeds, False otherwise
        """
        print("")

        while not bank_transactions.empty:
            print(f"Would you like to add {len(bank_transactions)} remaining "
                  f"transations manually?")
            for idx, row in bank_transactions.iterrows():
                self.print_line(idx, row)

            ans = input("(y/n):")
            if ans == "y":
                return True
            elif ans == "n":
                return False
            else:
                self._invalid_input()
                continue

    def print_report(self, transactions: pd.DataFrame) -> None:
        """Prints colored summary of bank transactions.

        Parameters
        ----------
        transactions : pd.DataFrame
            A table with transactions and their record status
        """

        for idx, row in transactions.iterrows():
            if row["is_in_ml"]:
                text = "In MoneyLover"
                color = TextColors.OKGREEN
            elif row["has_preset"]:
                text = "Recognized"
                color = TextColors.OKBLUE
            else:
                text = "Requires manual entry"
                color = TextColors.FAIL

            self.print_line(
                idx,
                row,
                text,
                color,
            )
        print(f"{TextColors.DEFAULT}")

    def print_line(self, idx:int, transaction: pd.Series, text="", color=""):
        """Prints the main transaction info in a formatted line

        Parameters
        ----------
        idx : int
            Transaction row index
        transaction : pd.Series
            Transaction to print
        text : str, optional
            Short text at the end, by default ""
        color : str, optional
            Color of the printed line, by default ""
        """

        name = transaction["name"]
        amount = transaction["amount"]
        tr_type = transaction["debit/credit"]
        date = transaction["date"].strftime("%d-%m-%Y")

        sign = {"Debit": "-", "Credit": "+"}.get(tr_type)

        name = name[:36] + "..." if len(name) > 40 else name[:40]
        print(
            f"{color}{idx:2}: {name:40}: {date:10} : {sign}{amount:10.2f} : {text}"
        )

    def prompt_adding(self, transactions: pd.DataFrame) -> bool:
        """Prompt automatic transfer of transactions using presets.

        Parameters
        ----------
        transactions : pd.DataFrame
            Transactions to be added through presets

        Returns
        -------
        bool
            True if user proceeds, False otherwise
        """

        if transactions.empty:
            return False

        print("Do you want to add following entries?")
        for idx, row in transactions.iterrows():
            self.print_line(idx, row)
        while True:
            ans = input("(y/n):")
            if ans == "y":
                return True
            elif ans == "n":
                return False
            else:
                self._invalid_input()
                continue

    def _invalid_input(self):

        print("Sorry, the input is not valid")


class CategorySelector:
    """Class responsible for the category selection from the dataframe
    
    Parameters
    ----------
    categories : DataFrame
        MoneyLover categories as dataframe (MoneyLoverClient attribute)
    
    """

    def __init__(self, categories: pd.DataFrame) -> None:
        self.categories = categories.drop_duplicates("name")
        self.selected_category: str | None

    def run(self) -> str | None:
        """Prints the available categories and asks for user input"""
        while True:
            self._display_categories()
            if self._category_selected():
                break
        return self.selected_category

    def _display_categories(self) -> None:
        """Prints parent categories"""
        os.system("cls" if os.name == "nt" else "clear")
        print("Available categories:\n")
        print(self.parent_categories[["name", "sub-categories"]])

        print("\nType in category number or 's' to skip transaction")

    def _category_selected(self) -> bool:
        """Handles user input and selection of the main and sub-categories.

        Returns
        -------
        bool
            True if category is selected or skipped, False otherwise
        """
        user_input = input("\n>> ")

        if user_input.isdigit():
            selected_index = int(user_input)
            if 0 <= selected_index < len(self.parent_categories):
                self.selected_category = self.parent_categories.at[
                    selected_index, "name"
                ]
                subcategories = self._get_children(self.selected_category)
                if subcategories.empty:
                    return True
                elif self._select_subcategory(subcategories):
                    return True
                else:
                    return False
        elif user_input.lower() == "s":
            print("Skipping transaction")
            self.selected_category = None
            return True

        return False

    def _select_subcategory(self, subcategories: pd.Series) -> str | None:
        """Handles sub-category selection
        
        Returns
        -------
        str | None
            Selected category name or None to return back
        """
        print("Select a subcategory:\n")
        print(subcategories.to_string())
        while True:
            print(
                f"\nType in sub-category number or 'b' to return back.\nPress"
                f" Enter to use parent category '{self.selected_category}'"
            )
            user_input = input("\n>> ")

            if user_input.isdigit():
                selected_index = int(user_input)
                if 0 <= selected_index < len(subcategories):
                    self.selected_category = subcategories.iloc[selected_index]
                    return self.selected_category
            elif user_input.lower() == "b":
                return None
            elif user_input == "":
                return self.selected_category

    @property
    def parent_categories(self) -> pd.DataFrame:
        """Returns top-level categories"""
        mask = self.categories["parent"].isna()
        return self._count_subcategories(self.categories[mask])

    def _count_subcategories(self, parents_df: pd.DataFrame) -> pd.DataFrame:
        """Count number of sub-categories"""
        children_count = self.categories["parent"].value_counts()
        children_count.rename("sub-categories", inplace=True)

        df = pd.merge(
            parents_df,
            children_count,
            left_on="_id",
            right_on="parent",
            how="left",
        )
        df["sub-categories"] = df["sub-categories"].fillna(0).astype(int)
        df["sub-categories"] = df["sub-categories"].replace(0, "")

        return df

    def _get_children(self, parent_category: str) -> pd.Series:
        """Return sub-categories of the parent."""
        parent = self.categories["name"] == parent_category
        parent_id = self.categories.loc[parent, "_id"].iloc[0]
        children_mask = self.categories["parent"] == str(parent_id)
        children = self.categories[children_mask]["name"].drop_duplicates()
        return children.reset_index(drop=True)


class TextColors:
    """Command line colors"""
    DEFAULT = "\u001b[37m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
