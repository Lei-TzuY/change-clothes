from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from flask import current_app, request
from sqlalchemy import func

from .extensions import db
from .models import CreditTransaction, ImageResult


DAILY_FREE_LIMIT = 10


def client_ip() -> str:
    try:
        # Prefer X-Forwarded-For if behind proxy
        xff = request.headers.get('X-Forwarded-For')
        if xff:
            return xff.split(',')[0].strip()
        return request.remote_addr or ''
    except Exception:
        return ''


def today_range() -> Tuple[datetime, datetime]:
    now = datetime.utcnow()
    start = datetime(year=now.year, month=now.month, day=now.day)
    end = start + timedelta(days=1)
    return start, end


def free_remaining(user_id: Optional[int], ip: str) -> int:
    # Allow disabling daily free limit in test mode
    try:
        if current_app and (
            current_app.config.get("DISABLE_DAILY_FREE_LIMIT")
            or current_app.config.get("TEST_MODE")
            or current_app.config.get("DISABLE_LIMITS")
        ):
            return 10**9  # effectively unlimited
    except Exception:
        pass

    start, end = today_range()
    q = db.session.query(func.count(ImageResult.id)).filter(ImageResult.created_at >= start, ImageResult.created_at < end)
    if user_id:
        q = q.filter(ImageResult.user_id == user_id)
    else:
        q = q.filter(ImageResult.request_ip == ip)
    count = int(q.scalar() or 0)
    remain = max(0, DAILY_FREE_LIMIT - count)
    return remain


def balance(user_id: int) -> float:
    total = db.session.query(func.coalesce(func.sum(CreditTransaction.amount), 0.0)).filter(CreditTransaction.user_id == user_id).scalar() or 0.0
    return float(total)


def compute_cost(kind: str, *, width: Optional[int] = None, height: Optional[int] = None, steps: Optional[int] = None, denoise: Optional[float] = None) -> float:
    # Base costs per kind
    base_map = {
        'text2image': 1.0,
        'img2img': 1.0,
        'inpaint': 1.0,
        'upload2': 1.0,
    }
    cost = base_map.get(kind, 1.0)
    try:
        # Resolution factor relative to 512x512
        if width and height:
            res_scale = max(width * height / (512 * 512), 1.0)
            cost += 0.5 * (res_scale - 1.0)
        # Steps factor around 30
        if steps:
            cost += max(0.0, (steps - 30) / 30.0) * 0.5
        # Denoise has mild effect
        if denoise is not None:
            cost += max(0.0, denoise - 0.6) * 0.5
    except Exception:
        pass
    # Round to 2 decimals
    return float(round(cost, 2))


def spend(user_id: int, amount: float, *, kind: str, reference: Optional[str] = None, meta: Optional[str] = None) -> None:
    tx = CreditTransaction(user_id=user_id, amount=-abs(amount), kind='spend', reference=reference, meta=meta)
    db.session.add(tx)
    db.session.commit()


def grant(user_id: int, amount: float, *, kind: str = 'purchase', reference: Optional[str] = None, meta: Optional[str] = None) -> None:
    tx = CreditTransaction(user_id=user_id, amount=abs(amount), kind=kind, reference=reference, meta=meta)
    db.session.add(tx)
    db.session.commit()
