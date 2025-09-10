import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_required

from backend.comfy import _fetch_object_info, _extract_choices


bp = Blueprint("settings", __name__)


@bp.get("/settings")
@login_required
def settings_page():
    ckpt_choices = []
    vae_choices = []
    err = None
    try:
        info = _fetch_object_info(current_app.config.get("COMFY_ADDR", "127.0.0.1:8188"))
        ckpt_choices = _extract_choices(info, "CheckpointLoaderSimple", "ckpt_name")
        vae_choices = _extract_choices(info, "VAELoader", "vae_name")
    except Exception as e:
        err = str(e)

    selected_ckpt = session.get("CKPT_NAME") or current_app.config.get("CKPT_NAME")
    selected_vae = session.get("VAE_NAME") or current_app.config.get("VAE_NAME")
    return render_template(
        "settings.html",
        ckpt_choices=ckpt_choices,
        vae_choices=vae_choices,
        selected_ckpt=selected_ckpt,
        selected_vae=selected_vae,
        error=err,
    )


@bp.post("/settings")
@login_required
def settings_save():
    session["CKPT_NAME"] = (request.form.get("ckpt_name") or "").strip() or None
    session["VAE_NAME"] = (request.form.get("vae_name") or "").strip() or None
    flash("設定已更新", "success")
    return redirect(url_for("settings.settings_page"))

