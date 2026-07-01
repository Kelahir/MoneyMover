"""Local Flask server giving a browser-based alternative to the MoneyMover CLI.

Serves the static webui/ frontend and exposes it a small JSON API backed by
the existing MoneyMover class. Single-user, single-process: the active
MoneyMover instance is held in a module-level variable, same as a CLI/Jupyter
session would hold `ml = MoneyMover(...)` in memory.

Run with: python webapp.py
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from money_mover import MoneyMover
from money_mover.moneylover_api import MoneyLoverClient

WEBUI_DIR = Path(__file__).resolve().parent / "webui"
BANK_STATEMENTS_DIR = Path(__file__).resolve().parent / "bank_statements"
ENV_PATH = Path(__file__).resolve().parent / ".env"

app = Flask(__name__, static_folder=str(WEBUI_DIR), static_url_path="")

_session = {"mover": None}


def _env_credentials() -> tuple[str | None, str | None]:
    """Reads EMAIL/PASSWORD straight from .env on every call.

    Deliberately not `load_dotenv()` + `os.getenv()`: that copies values into
    the process environment once and never re-reads the file, so deleting or
    editing .env wouldn't be reflected until the server process restarts.
    """
    values = dotenv_values(ENV_PATH)
    return values.get("EMAIL"), values.get("PASSWORD")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


def _wallets_payload(mover: MoneyMover) -> list[dict]:
    # The MoneyLover API returns balance as a string; normalize to a real
    # number so the frontend doesn't have to guess the wire type.
    df = mover.wallets.copy()
    df["balance"] = df["balance"].astype(float)
    return df.to_dict(orient="records")


def _statement_payload(mover: MoneyMover) -> dict:
    statement = mover.bank_statement
    if statement.transactions.empty:
        return {"found": False}

    start, end = statement.date_range
    return {
        "found": True,
        "filename": statement.filename,
        "date_range": [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")],
    }


def _transactions_payload(df: pd.DataFrame, ml_transactions: pd.DataFrame) -> list[dict]:
    records = []
    for position, (_, row) in enumerate(df.iterrows()):
        if row["is_in_ml"]:
            origin = "existing"
        elif row["is_possible_duplicate"]:
            origin = "possible_duplicate"
        elif row["has_preset"]:
            origin = "preset"
        else:
            origin = "manual"

        # The bank statement's own sign convention isn't guaranteed, so
        # normalize using the explicit debit/credit column instead (same
        # convention prompts.py already uses for CLI display).
        sign = -1 if row["debit/credit"] == "Debit" else 1

        tx_type = row.get("type")
        if pd.isna(tx_type):
            tx_type = "expense" if row["debit/credit"] == "Debit" else "income"

        category = row.get("category_name")
        if pd.isna(category):
            category = None

        duplicate_dates = None
        if origin == "possible_duplicate":
            # Same amount match, matched against the raw (unsigned) amount
            # the same way _check_if_already_added does - so the dates
            # shown are exactly what triggered the flag.
            matches = ml_transactions[ml_transactions["amount"] == row["amount"]]
            duplicate_dates = sorted({d.strftime("%Y-%m-%d") for d in matches["date"]})

        records.append(
            {
                "id": position,
                "date": row["date"].strftime("%Y-%m-%d"),
                "note": row["name"],
                "amount": round(sign * abs(row["amount"]), 2),
                "category": category,
                "type": tx_type,
                "origin": origin,
                "duplicateDates": duplicate_dates,
            }
        )
    return records


def _categories_payload(mover: MoneyMover) -> dict:
    """Nests the wallet's flat category list into {type: {parent: [children]}},
    matching the shape the frontend's category/sub-category dropdowns expect.
    Debt/loan categories are skipped - the UI only offers expense/income.
    """
    df = mover.wallet_categories.drop_duplicates("name")
    result: dict[str, dict[str, list[str]]] = {}

    for tx_type in ("expense", "income"):
        type_df = df[df["type"] == tx_type]
        parents = type_df[type_df["parent"].isna()]

        categories = {}
        for _, parent in parents.iterrows():
            children_mask = type_df["parent"] == str(parent["_id"])
            categories[parent["name"]] = type_df[children_mask]["name"].tolist()
        result[tx_type] = categories

    return result


@app.get("/api/session")
def get_session():
    """Instant check: is there already a session live in this server process?"""
    if _session["mover"] is None:
        return jsonify({"authenticated": False})
    return jsonify(
        {"authenticated": True, "wallets": _wallets_payload(_session["mover"])}
    )


@app.post("/api/logout")
def logout():
    """Ends the active session without touching the cached token file, so
    /api/auth-status can immediately offer to log back in with it."""
    _session["mover"] = None
    return jsonify({"ok": True})


@app.get("/api/auth-status")
def auth_status():
    """Reports which login method is available, without logging in.

    Side-effect-free and fast, so the frontend can show "previous session
    found" / "credentials found in .env" and let the user opt in, rather
    than silently auto-logging in with no feedback.
    """
    if MoneyLoverClient.has_cached_session():
        return jsonify(
            {
                "method": "token",
                "days_left": MoneyLoverClient.cached_session_days_left(),
            }
        )

    email, password = _env_credentials()
    if email and password:
        return jsonify({"method": "env", "email": email})

    return jsonify({"method": "none"})


@app.post("/api/login")
def login():
    """Logs in with explicit credentials, or "continues" with whatever
    /api/auth-status reported (cached token or .env) if the body is empty.
    """
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email and not password:
        if not MoneyLoverClient.has_cached_session():
            email, password = _env_credentials()
            if not (email and password):
                return (
                    jsonify({"error": "No saved session or .env credentials found."}),
                    400,
                )
        # else: leave email/password as None - MoneyLoverClient reuses the
        # cached token itself and never touches them.

    try:
        _session["mover"] = MoneyMover(email, password)
    except Exception as e:
        return jsonify({"error": str(e)}), 401

    return jsonify({"wallets": _wallets_payload(_session["mover"])})


@app.post("/api/wallets/select")
def select_wallet():
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "wallet_id is required."}), 400

    try:
        mover.select_wallet(wallet_id)
    except IndexError:
        return jsonify({"error": f"No wallet with id {wallet_id}"}), 404

    return jsonify(
        {"wallet_name": mover.active_wallet_name, "wallet_id": mover.active_wallet_id}
    )


@app.get("/api/categories")
def get_categories():
    """Real expense/income category and sub-category names for the active
    wallet, for the manual-entry dropdowns."""
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401
    if not hasattr(mover, "wallet_categories"):
        return jsonify({"error": "No wallet selected."}), 400

    return jsonify(_categories_payload(mover))


@app.get("/api/statement")
def get_statement():
    """Reports the bank statement MoneyMover already auto-detected at login."""
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401

    return jsonify(_statement_payload(mover))


@app.post("/api/statement/upload")
def upload_statement():
    """Lets the user pick a specific .csv instead of relying on auto-detect."""
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "No file uploaded."}), 400

    filename = secure_filename(uploaded.filename)
    if not filename.lower().endswith(".csv"):
        return jsonify({"error": "Only .csv files are supported."}), 400

    BANK_STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = BANK_STATEMENTS_DIR / filename
    uploaded.save(saved_path)

    try:
        mover.load_bank_statement(str(saved_path))
    except Exception as e:
        return jsonify({"error": f"Could not parse {filename}: {e}"}), 400

    return jsonify(_statement_payload(mover))


@app.get("/api/transactions/review")
def review_transactions():
    """Compares the loaded bank statement against MoneyLover and presets.

    Read-only: does not add anything to MoneyLover yet.
    """
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401
    if mover.bank_statement.transactions.empty:
        return jsonify({"error": "No bank statement loaded."}), 400

    try:
        df = mover.get_bank_report()
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"transactions": _transactions_payload(df, mover.ml_transactions)})


@app.post("/api/transactions/insert-recognized")
def insert_recognized():
    """Writes every preset-matched, not-yet-in-MoneyLover transaction to the
    active wallet. This is a real write - it creates actual records in the
    user's MoneyLover account.
    """
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401

    try:
        inserted = mover.insert_recognized_transactions()
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"inserted": len(inserted)})


@app.post("/api/transactions/manual")
def add_manual_transaction():
    """Writes a single manually-filled-in transaction to the active wallet.
    Also a real write, same as above.
    """
    mover = _session["mover"]
    if mover is None:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    required = ["date", "amount", "type", "category", "note"]
    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        date = datetime.strptime(data["date"], "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "date must be in YYYY-MM-DD format."}), 400

    category_name = data.get("subcategory") or data["category"]

    try:
        mover.add_manual_transaction(
            amount=float(data["amount"]),
            date=date,
            category_name=category_name,
            transaction_type=data["type"],
            note=data["note"],
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(port=5000, debug=True)
