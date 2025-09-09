from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
import requests
import re

from app.extensions import db
from app.models import User


bp = Blueprint("auth", __name__)


def _verify_recaptcha(token: str, remote_ip: str | None = None) -> bool:
    secret = current_app.config.get("RECAPTCHA_SECRET_KEY", "")
    if not secret:
        # If not configured, treat as failed for safety
        return False
    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        resp = requests.post("https://www.google.com/recaptcha/api/siteverify", data=data, timeout=6)
        payload = resp.json()
        return bool(payload.get("success"))
    except Exception:
        return False


@bp.get("/register")
def register_form():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    site_key = current_app.config.get("RECAPTCHA_SITE_KEY", "")
    return render_template("register.html", recaptcha_site_key=site_key)


@bp.post("/register")
def register_submit():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    token = request.form.get("g-recaptcha-response") or ""

    # Basic validation
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Email 格式不正確", "error")
        return redirect(url_for("auth.register_form"))
    if len(password) < 8:
        flash("密碼至少 8 碼", "error")
        return redirect(url_for("auth.register_form"))

    # Verify reCAPTCHA
    if not _verify_recaptcha(token, request.remote_addr):
        flash("reCAPTCHA 驗證失敗，請再試一次", "error")
        return redirect(url_for("auth.register_form"))

    # Create user
    try:
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Email 已被註冊", "error")
        return redirect(url_for("auth.register_form"))

    login_user(user)
    flash("註冊成功，已自動登入", "success")
    return redirect(url_for("main.index"))


@bp.get("/login")
def login_form():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    return render_template("login.html")


@bp.post("/login")
def login_submit():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("帳號或密碼錯誤", "error")
        return redirect(url_for("auth.login_form"))

    login_user(user)
    flash("登入成功", "success")
    return redirect(url_for("main.index"))


@bp.post("/logout")
@login_required
def logout_submit():
    logout_user()
    flash("已登出", "success")
    return redirect(url_for("main.index"))

