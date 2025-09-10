from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
import requests
import re

from app.extensions import db, limiter
from app.models import User
from backend.tokens import generate_email_token, confirm_email_token
from backend.email_utils import send_mail


bp = Blueprint("auth", __name__)


def _keys_and_domain():
    cfg = current_app.config
    site = cfg.get("RECAPTCHA_SITE_KEY", "")
    secret = cfg.get("RECAPTCHA_SECRET_KEY", "")
    domain = cfg.get("RECAPTCHA_SCRIPT_DOMAIN", "www.google.com")
    use_test = cfg.get("RECAPTCHA_USE_TEST_KEYS", False) or current_app.debug
    # Fallback to Google test keys in development
    if (not site or not secret) and use_test:
        site = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
        secret = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"
    return site, secret, domain


def _verify_recaptcha(token: str, remote_ip: str | None = None) -> bool:
    _, secret, domain = _keys_and_domain()
    if not secret:
        # Not configured and not allowed to use test keys
        return False
    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        resp = requests.post(f"https://{domain}/recaptcha/api/siteverify", data=data, timeout=6)
        payload = resp.json()
        return bool(payload.get("success"))
    except Exception:
        return False


@bp.get("/register")
def register_form():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    site_key, _, domain = _keys_and_domain()
    return render_template(
        "register.html",
        recaptcha_site_key=site_key,
        recaptcha_domain=domain,
    )


@bp.post("/register")
def register_submit():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm_password") or ""
    token = request.form.get("g-recaptcha-response") or ""

    # Basic validation
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Email 格式不正確", "error")
        return redirect(url_for("auth.register_form"))
    if len(password) < 8:
        flash("密碼至少 8 碼", "error")
        return redirect(url_for("auth.register_form"))
    if password != confirm:
        flash("兩次輸入的密碼不一致", "error")
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

    # Send verification email
    try:
        token = generate_email_token(email)
        verify_link = url_for("auth.verify_email", token=token, _external=True)
        html = f"""
        <h3>您好，歡迎加入！</h3>
        <p>請點擊以下連結完成信箱驗證：</p>
        <p><a href="{verify_link}">{verify_link}</a></p>
        <p>此連結將在 72 小時後失效。</p>
        """
        send_mail(email, "請驗證您的電子信箱", html, text=f"請開啟連結完成驗證: {verify_link}")
        if current_app.config.get("MAIL_DEV_PRINT"):
            flash(f"註冊成功（開發模式），直接點此驗證： {verify_link}", "success")
        else:
            flash("註冊成功，請至信箱點擊驗證連結。", "success")
    except Exception as e:
        current_app.logger.exception("寄送驗證信失敗")
        flash("註冊成功，但寄送驗證信失敗，請稍後從登入頁重寄驗證信。", "error")

    return redirect(url_for("auth.login_form"))


@bp.get("/login")
def login_form():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    return render_template("login.html")


@bp.post("/login")
@limiter.limit("10/minute")
def login_submit():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("帳號或密碼錯誤", "error")
        return redirect(url_for("auth.login_form"))

    if not user.email_verified:
        flash("此帳號尚未完成信箱驗證，請至信箱收取驗證信或點此重寄。", "error")
        return redirect(url_for("auth.resend_verify_form", email=user.email))

    remember = request.form.get("remember") == "on"
    login_user(user, remember=remember)
    flash("登入成功", "success")
    return redirect(url_for("main.index"))


@bp.post("/logout")
@login_required
def logout_submit():
    logout_user()
    flash("已登出", "success")
    return redirect(url_for("main.index"))


@bp.get("/profile")
@login_required
def profile_page():
    return render_template("profile.html")


@bp.get("/password")
@login_required
def password_form():
    return render_template("change_password.html")


@bp.post("/password")
@login_required
@limiter.limit("5/hour")
def password_submit():
    old = request.form.get("old_password") or ""
    new = request.form.get("new_password") or ""
    if len(new) < 8:
        flash("新密碼至少 8 碼", "error")
        return redirect(url_for("auth.password_form"))
    if not current_user.check_password(old):
        flash("原密碼不正確", "error")
        return redirect(url_for("auth.password_form"))
    current_user.set_password(new)
    db.session.commit()
    flash("密碼已更新", "success")
    return redirect(url_for("auth.profile_page"))


@bp.get("/verify")
def verify_email():
    token = request.args.get("token", "")
    email = confirm_email_token(token)
    if not email:
        flash("驗證連結無效或已過期，請重寄驗證信。", "error")
        return redirect(url_for("auth.resend_verify_form"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("找不到對應的帳號。", "error")
        return redirect(url_for("auth.login_form"))
    if user.email_verified:
        flash("此信箱已完成驗證，請直接登入。", "success")
        return redirect(url_for("auth.login_form"))

    user.email_verified = True
    from datetime import datetime
    user.verified_at = datetime.utcnow()
    db.session.commit()
    flash("信箱驗證完成，請登入。", "success")
    return redirect(url_for("auth.login_form"))


@bp.get("/resend")
def resend_verify_form():
    email = request.args.get("email", "")
    return render_template("resend_verify.html", email=email)


@bp.post("/resend")
@limiter.limit("5/hour")
def resend_verify_submit():
    email = (request.form.get("email") or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Email 格式不正確", "error")
        return redirect(url_for("auth.resend_verify_form"))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash("找不到此 Email 的帳號", "error")
        return redirect(url_for("auth.resend_verify_form"))
    if user.email_verified:
        flash("此信箱已驗證，請直接登入。", "success")
        return redirect(url_for("auth.login_form"))

    try:
        token = generate_email_token(email)
        verify_link = url_for("auth.verify_email", token=token, _external=True)
        html = f"""
        <h3>重新寄送驗證信</h3>
        <p>請點擊以下連結完成信箱驗證：</p>
        <p><a href="{verify_link}">{verify_link}</a></p>
        """
        send_mail(email, "重新寄送驗證信", html, text=f"請開啟連結完成驗證: {verify_link}")
        if current_app.config.get("MAIL_DEV_PRINT"):
            flash(f"已產生驗證連結（開發模式）： {verify_link}", "success")
        else:
            flash("驗證信已寄出，請至信箱收信。", "success")
    except Exception:
        current_app.logger.exception("重寄驗證信失敗")
        flash("寄送失敗，請稍後再試。", "error")
    return redirect(url_for("auth.login_form"))
