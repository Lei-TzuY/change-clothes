from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.billing import balance, grant


bp = Blueprint("billing", __name__)


@bp.get("/billing")
@login_required
def billing_page():
    bal = balance(current_user.id)
    return render_template("billing.html", balance=bal)


@bp.post("/billing/purchase")
@login_required
def billing_purchase():
    # 開發用購買入口：直接加點數，未接金流
    try:
        amount = float(request.form.get("amount", "0"))
    except Exception:
        return jsonify(error="amount 需為數字"), 400
    if amount <= 0:
        return jsonify(error="amount 必須 > 0"), 400
    grant(current_user.id, amount, kind='purchase')
    return jsonify(message="已加值", balance=balance(current_user.id))


@bp.get("/billing/balance")
@login_required
def billing_balance():
    return jsonify(balance=balance(current_user.id))

