from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user

from app.extensions import db, csrf, limiter
from app.models import ImageResult, ImageRating, SurveyResponse


bp = Blueprint("feedback", __name__)


@bp.get("/survey")
def survey_form():
    return render_template("survey.html")


@bp.post("/survey/submit")
@limiter.limit("30/hour")
def survey_submit():
    def _as_int(name: str):
        v = request.form.get(name)
        try:
            return int(v) if v is not None and v != "" else None
        except Exception:
            return None

    s = SurveyResponse(
        user_id=(current_user.id if getattr(current_user, "is_authenticated", False) else None),
        q1=_as_int("q1"),
        q2=_as_int("q2"),
        q3=_as_int("q3"),
        q4=_as_int("q4"),
        q5=_as_int("q5"),
        suggestion=(request.form.get("suggestion") or "").strip() or None,
    )
    db.session.add(s)
    db.session.commit()
    return render_template("survey.html", success=True)


@bp.post("/rate")
@limiter.limit("120/hour")
@csrf.exempt
def rate_image():
    data = request.get_json(silent=True) or request.form
    img_id = data.get("image_id")
    filename = data.get("filename")
    try:
        rating_val = int(data.get("rating"))
    except Exception:
        return jsonify(error="rating 需為 1~5 整數"), 400
    if rating_val < 1 or rating_val > 5:
        return jsonify(error="rating 超出範圍 (1-5)"), 400

    img: ImageResult | None = None
    if img_id:
        img = ImageResult.query.get(int(img_id))
    if not img and filename:
        img = ImageResult.query.filter_by(filename=filename).first()
    if not img:
        return jsonify(error="找不到圖片"), 404

    # If user logged-in, update existing rating; else create anonymous
    user_id = current_user.id if getattr(current_user, "is_authenticated", False) else None
    rec = None
    if user_id:
        rec = ImageRating.query.filter_by(image_id=img.id, user_id=user_id).first()
    if rec:
        rec.rating = rating_val
        cmt = (data.get("comment") or "").strip()
        rec.comment = cmt or rec.comment
    else:
        rec = ImageRating(image_id=img.id, user_id=user_id, rating=rating_val, comment=(data.get("comment") or "").strip() or None)
        db.session.add(rec)
    db.session.commit()

    # Aggregate
    from sqlalchemy import func

    agg = db.session.query(func.count(ImageRating.id), func.avg(ImageRating.rating)).filter(ImageRating.image_id == img.id).first()
    count = int(agg[0] or 0)
    avg = float(agg[1] or 0.0)
    return jsonify(message="已送出評分", image_id=img.id, filename=img.filename, rating=rating_val, avg=round(avg, 2), count=count)

