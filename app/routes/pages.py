from flask import Blueprint, render_template, current_app
from backend.comfy import get_model_options

bp = Blueprint('pages', __name__)


@bp.route('/t2i')
def page_t2i():
    opts = get_model_options(current_app.config.get("COMFY_ADDR", "127.0.0.1:8188"))
    return render_template('t2i.html', **opts)


@bp.route('/i2i')
def page_i2i():
    opts = get_model_options(current_app.config.get("COMFY_ADDR", "127.0.0.1:8188"))
    return render_template('i2i.html', **opts)


@bp.route('/inpaint')
def page_inpaint():
    opts = get_model_options(current_app.config.get("COMFY_ADDR", "127.0.0.1:8188"))
    return render_template('inpaint.html', **opts)


@bp.route('/i2v')
def page_i2v():
    return render_template('i2v.html')
