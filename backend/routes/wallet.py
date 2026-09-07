from flask import Blueprint, request, jsonify
from services.auth import require_login
from services.wallet_service import get_wallet, credit


wallet_bp = Blueprint("wallet", __name__)


def _view(w):
    txns = sorted(w.get("transactions") or [], key=lambda t: t.get("createdAt", ""), reverse=True)
    return {
        "walletId": str(w["_id"]),
        "balance": round(float(w.get("balance") or 0), 2),
        "totalDeposited": round(float(w.get("totalDeposited") or 0), 2),
        "totalSpent": round(float(w.get("totalSpent") or 0), 2),
        "currency": w.get("currency", "INR"),
        "transactions": txns,
    }


@wallet_bp.route("/api/wallet", methods=["GET"])
@require_login
def wallet_view():
    return jsonify(_view(get_wallet(request.current_user["id"])))


@wallet_bp.route("/api/wallet/deposit", methods=["POST"])
@require_login
def wallet_deposit():
    amount = (request.get_json() or {}).get("amount")
    wallet, err = credit(request.current_user["id"], amount, description="Wallet top-up")
    if err:
        return jsonify({"error": err}), 400
    return jsonify(_view(wallet))