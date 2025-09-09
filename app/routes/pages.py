from flask import Blueprint, render_template

bp = Blueprint('pages', __name__)


@bp.route('/t2i')
def page_t2i():
    return render_template('t2i.html')


@bp.route('/i2i')
def page_i2i():
    return render_template('i2i.html')


@bp.route('/inpaint')
def page_inpaint():
    return render_template('inpaint.html')

