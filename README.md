# MoneyMover - Money Lover transaction transfer interface
## About
Money Lover is a mobile app, which allows to manage personal finances. However, after moving to the Netherlands most of my spendings go through the card payment. I quickly found myself manually moving the same records from my bank statements every month.

This script automates the process of adding the known transactions from the bank statement (ING) to your MoneyLover account. For the transactions which do not have a preset, there is an interface to add them in.

### Bank statements
The parser supports the .csv statements from the ING bank. I simply don't have access to other ones to implement. You can write a custom parser class using
the abstract class in the ing_parser.py.

## How to install
- Download the project files
- Install Python virtual environment (developed on version 3.12)
- Install required packages with `pip install -r requirements.txt`

## How to use
### 1. Connect to the MoneLover API
Import the main class `from money_mover import MoneyMover` and create its instance. You will need to supply it with your MoneyLover email and password. There are three ways to pass them:
- Do not pass email and password arguments to the class. You will be prompted to enter them in the terminal.
- Create a .env file with your EMAIL and PASSWORD environment variables. Use dotenv module and its `load_dotenv()` function to load the variables.
- Pass them in plain text as arguments to the class (Not recommended).

After the log in, the script will request a token, which is valid for 5 days. You don't need to enter your credentials every time. Token is stored in `./money_mover/resources/access_token.txt`.
### 2. Display wallet info
Now you can display your MoneyLover data:
- `.wallets` attribute returns your wallet summary
- `set_wallet()` sets an active wallet for other methods, like:
    - `.this_month` and `.previous_month` attributes return records for the set wallet for the current and previous months respectively.
    - `request_transactions()` allows you to show records for the custom range of dates.
    - `display_categories()` shows an interactive menu with all available category names.
### 3. Parsing ING bank statements
Download your bank statement from your account options in a csv format. Put the csv file in the `./bank_statements` folder, which is the default path.
Now you can also run `print_bank_report()` to compare transactions in the bank statement with the ones you already have in the MoneyLover for that time period. Neat!

You can already run `transfer_bank_transactions()` and add the transactions one by one manually.
> **Note:**
> Transactions are compared by date and value. If you have multiple transactions on the same date and with the same value they all will be marked.
### 4. Preparing presets and auto-transfer
Navigate to `./money_mover/resources/` and create a custom preset file based on the `example_presets.json`. By default it is called `user_presets.json`. In this file you can mark transactions you know by name, value, description and so on. You can add as many entries as you require there. You define a filter in "conditions" and how you want to add it to MoneyLover in "label". You don't need an exact match for the fields, you can use regular expressions.

Now you can display your presets using `print_user_presets()` method. `print_bank_report()` will also highlight matches for you! Running a `transfer_bank_transactions()` will show you matches with your presets and offer to populate all these records for you.

## Examples
Check `example.py` or `example.ipynb` for the main methods.

## Thanks
Huge thanks to https://github.com/leMaik/moneylover-cli. I learned how to communicate with MoneyLover API from their project. If you prefer manual CLI interface, check the project out.