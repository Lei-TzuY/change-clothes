from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from typing import Optional

from flask import current_app


def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config["SECRET_KEY"]
    salt = current_app.config.get("SECURITY_PASSWORD_SALT", "email-verify")
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)


def generate_email_token(email: str) -> str:
    s = _serializer()
    return s.dumps({"email": email})


def confirm_email_token(token: str, max_age: int = 60 * 60 * 24 * 3) -> Optional[str]:
    s = _serializer()
    try:
        data = s.loads(token, max_age=max_age)
        return data.get("email")
    except (BadSignature, SignatureExpired):
        return None

