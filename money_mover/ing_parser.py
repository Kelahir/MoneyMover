"""ING bank statement parser.

Parses a csv bank account statement from ING. The columns are renamed, so both
NL and EN versions should work fine.

Some of the column names are used later, e.g. date, amount, name, so they are
assigned to a constant. Column names are also used for transaction presets.
If you need to parse other bank statements, make sure these columns exist.
"""

import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import pandas as pd

COLUMNS = [
    "date",
    "name",
    "account",
    "counterparty",
    "code",
    "debit/credit",
    "amount",
    "transaction type",
    "notifications",
]


class BankStatementParser(ABC):
    """Abstract base class for parsing bank statements.

    Parameters
    ----------
    statement_folder : str, optional
        Path to the folder with bank statements, './bank_statements/' by default

    Attributes
    ----------
    transactions : pd.DataFrame
        A table with transactions from the bank statement

    date_range : Tuple[datetime, datetime]
        Start and end dates of the bank statement
    """

    def __init__(self, statement_folder: str = "./bank_statements/") -> None:
        self.transactions: pd.DataFrame
        self.date_range: tuple[datetime, datetime]
        self._recent_bank_statement: Path
        self._bank_statement_folder = statement_folder
        self._find_statement()
        self._parse_statement()

    @abstractmethod
    def _find_statement(self) -> None:
        """Method to locate the file and set _recent_bank_statement"""

    @abstractmethod
    def _parse_statement(self) -> pd.DataFrame:
        """Method to parse _recent_bank_statement and assign attributes"""


class IngParser(BankStatementParser):
    """Parses the ING bank statement to retrieve transactions

    Parameters
    ----------
    statement_folder : str, optional
        Path to the folder with bank statements, './bank_statements/' by default

    Attributes
    ----------
    transactions : DataFrame
        A table with transactions from the bank statement

    date_range : tuple[datetime, datetime]
        Start and end dates of the bank statement

    """

    def _parse_statement(self) -> pd.DataFrame:
        """
        Parse and format statement .csv file to a DataFrame.
        """
        df = pd.read_csv(self._recent_bank_statement, header=0, names=COLUMNS)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df["amount"] = df["amount"].str.replace(",", ".").astype("float64")
        self.transactions = df

        return df

    def _find_closest_end_date_file(
        self, file_match: list[re.Match | None]
    ) -> str:
        """Parses the dates from the file names and returns the file with the
        latest range.

        Parameters
        ----------
        file_match : list[re.Match  |  None]
            List of files, which matched ING fname structure

        Returns
        -------
        str
            Latest statement .csv file
        """
        today = datetime.today()
        recent_file = None
        closest_days_diff = float("inf")

        for match in file_match:
            if match is None:
                continue

            _, start_date, end_date = match.groups()
            end_date = datetime.strptime(end_date, "%d-%m-%Y")
            start_date = datetime.strptime(start_date, "%d-%m-%Y")

            days_diff = (today - end_date).days

            if days_diff < closest_days_diff:
                closest_days_diff = days_diff
                recent_file = match.string
                self.date_range = (start_date, end_date)
        if isinstance(recent_file, str):
            return recent_file

        raise FileNotFoundError("ING bank statement is not found")

    def _find_statement(self) -> None:
        """Find latest bank statement .csv in the root folder.

        Returns
        -------
        Path
            Returns path to file
        """
        root_path = Path(self._bank_statement_folder)
        csv_files = list(root_path.glob("*.csv"))

        # The target fname looks as: (IBAN)_(datefrom)_(dateto).csv
        file_pattern = r"(.+)_(\d{2}-\d{2}-\d{4})_(\d{2}-\d{2}-\d{4})"

        file_matches = [
            re.match(file_pattern, file.name) for file in csv_files
        ]

        recent_file = self._find_closest_end_date_file(file_matches)
        self._recent_bank_statement = root_path.joinpath(recent_file)
