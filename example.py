import os
from datetime import datetime

from dotenv import load_dotenv

from money_mover import MoneyMover, MoneyMoverCLI

# %% Print wallet summary in your account
load_dotenv()
email = os.getenv("EMAIL")
password = os.getenv("PASSWORD")

ml = MoneyMover(
    email,
    password,
    bank_statement_folder="./tests",
    presets_fname="example_presets.json",
)
cli = MoneyMoverCLI(ml)

# %% Print wallet summary in your account
print("Your wallet summary:")
print(ml.wallets)
print()

# Set an active wallet to work with
cli.set_wallet()

# Display entries in MoneyLover for the selected wallet
print("Current month entries:")
print(ml.this_month)
print("Previous month entries:")
print(ml.previous_month)

# Display entries in custom time period
print("Custom transactions:")
start_date = datetime.fromisoformat("20231215")
end_date = datetime.fromisoformat("20231231")
print(ml.request_transactions((start_date, end_date)))

# %% Display and navigate through the categories in the wallet. Clears the terminal
cli.display_categories("expense")

# %% Print your report, comparing transactions in MoneyLover, bank and your preset
cli.print_bank_report()

# Print all your presets in a table
print("User presets:")
cli.print_user_presets()

# Run this to populate the transactions, which are not in your wallet.
# You will be prompted if you want to add them, so it is safe to run.
# WARNING: if you choose yes, the records from the example will be added!
cli.transfer_bank_transactions()
