"""Wallet data layer: per-user balance with append-only transactions.

Debits are atomic — a single guarded find_one_and_update means concurrent
bookings can never overspend a wallet (the update only applies when the
balance can cover the amount).
"""
from datetime import datetime
from bson.objectid import ObjectId
from services.mongodb import get_collection

MAX_DEPOSIT = 1_000_000


def _txn_id():
    return "W" + str(ObjectId())[-8:].upper()


def _now():
    return datetime.utcnow().isoformat()


def get_wallet(user_id):
    """Return the wallet document, creating an empty one if missing."""
    doc = get_collection("wallets").find_one({"_id": str(user_id)})
    if doc:
        return doc
    now = _now()
    wallet = {
        "_id": str(user_id),
        "userId": str(user_id),
        "balance": 0.0,
        "totalDeposited": 0.0,
        "totalSpent": 0.0,
        "currency": "INR",
        "createdAt": now,
        "updatedAt": now,
        "transactions": [],
    }
    try:
        get_collection("wallets").insert_one(wallet)
    except Exception:
        pass
    return get_collection("wallets").find_one({"_id": str(user_id)}) or wallet


def credit(user_id, amount, description="", ref=None):
    """Add funds to the wallet. Returns (wallet, err)."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None, "Amount must be a number."
    if amount <= 0:
        return None, "Amount must be positive."
    if amount > MAX_DEPOSIT:
        return None, "Amount exceeds the single-deposit limit."
    now = _now()
    txn = {
        "id": _txn_id(),
        "type": "DEPOSIT",
        "amount": round(amount, 2),
        "description": description or "Wallet top-up",
        "ref": ref,
        "balance": None,
        "createdAt": now,
    }
    get_collection("wallets").update_one(
        {"_id": str(user_id)},
        {"$setOnInsert": {
            "_id": str(user_id), "userId": str(user_id), "currency": "INR",
            "createdAt": now},
         "$set": {"updatedAt": now},
         "$inc": {"balance": round(amount, 2), "totalDeposited": round(amount, 2)},
         "$push": {"transactions": txn}},
        upsert=True,
    )
    wallet = get_collection("wallets").find_one({"_id": str(user_id)})
    if wallet:
        get_collection("wallets").update_one(
            {"_id": str(user_id), "transactions.id": txn["id"]},
            {"$set": {"transactions.$.balance": round(float(wallet.get("balance") or 0), 2)}})
    return wallet, None


def debit(user_id, amount, description="", ref=None):
    """Atomically deduct funds. Returns (wallet, err).

    Only matches when balance >= amount, so no two concurrent debits can
    overspend the wallet.
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None, "Amount must be a number."
    if amount <= 0:
        return None, "Amount must be positive."
    now = _now()
    txn = {
        "id": _txn_id(),
        "type": "DEBIT",
        "amount": round(-amount, 2),
        "description": description or "Payment",
        "ref": ref,
        "balance": None,
        "createdAt": now,
    }
    wallet = get_collection("wallets").find_one_and_update(
        {"_id": str(user_id), "balance": {"$gte": amount}},
        {"$set": {"updatedAt": now},
         "$inc": {"balance": round(-amount, 2), "totalSpent": round(amount, 2)},
         "$push": {"transactions": txn}},
        return_document=True,
    )
    if not wallet:
        return None, "Insufficient wallet balance."
    get_collection("wallets").update_one(
        {"_id": str(user_id), "transactions.id": txn["id"]},
        {"$set": {"transactions.$.balance": round(float(wallet.get("balance") or 0), 2)}})
    return wallet, None