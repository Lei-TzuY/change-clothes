from flask import Blueprint, render_template
from flask_login import current_user

from app.models import ImageResult


bp = Blueprint("gallery", __name__)


@bp.get("/gallery")
def gallery_page():
    # Show recent 60 for now
    images = ImageResult.query.order_by(ImageResult.created_at.desc()).limit(60).all()
    return render_template("gallery.html", images=images)

