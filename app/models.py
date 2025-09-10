from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class ImageResult(db.Model):
    __tablename__ = "image_results"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    kind = db.Column(db.String(50), nullable=False)  # upload2|text2image|img2img|inpaint
    source_path = db.Column(db.String(1024))
    output_path = db.Column(db.String(1024))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Billing-related
    cost_credits = db.Column(db.Float, default=0.0, nullable=False)
    request_ip = db.Column(db.String(64))

    user = db.relationship("User", backref=db.backref("images", lazy=True))


class ImageRating(db.Model):
    __tablename__ = "image_ratings"

    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey("image_results.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    image = db.relationship("ImageResult", backref=db.backref("ratings", lazy=True))
    user = db.relationship("User", backref=db.backref("ratings", lazy=True))


class SurveyResponse(db.Model):
    __tablename__ = "survey_responses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    q1 = db.Column(db.Integer, nullable=True)
    q2 = db.Column(db.Integer, nullable=True)
    q3 = db.Column(db.Integer, nullable=True)
    q4 = db.Column(db.Integer, nullable=True)
    q5 = db.Column(db.Integer, nullable=True)
    suggestion = db.Column(db.Text, nullable=True)

    user = db.relationship("User", backref=db.backref("surveys", lazy=True))


class CreditTransaction(db.Model):
    __tablename__ = "credit_transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # amount: + purchase / grant; - spend
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(16), default="credit", nullable=False)
    kind = db.Column(db.String(50), nullable=False)  # purchase|spend|adjust|grant
    reference = db.Column(db.String(128))  # e.g., image:<id>
    meta = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref=db.backref("credit_transactions", lazy=True))
