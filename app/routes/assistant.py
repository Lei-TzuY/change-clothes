from __future__ import annotations

import os
import time
from typing import Any, Dict, List

import requests
from flask import Blueprint, jsonify, request
from app.extensions import csrf, limiter


bp = Blueprint("assistant", __name__)
csrf.exempt(bp)


def _openai_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


@bp.get("/assistant/config")
def assistant_config():
    return jsonify({
        "llm": {
            "provider": "openai" if _openai_available() else "offline",
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "enabled": _openai_available(),
        }
    })


@bp.post("/assistant/chat")
@limiter.limit("30/minute")
def assistant_chat():
    data = request.get_json(silent=True) or {}
    messages: List[Dict[str, str]] = data.get("messages") or []
    user_msg: str = (data.get("message") or "").strip()
    path: str = (data.get("path") or request.headers.get("X-Page-Path") or "/").strip()

    if not user_msg and not messages:
        return jsonify(error="請提供訊息"), 400

    # Normalize messages list (append current user message if provided)
    if user_msg:
        messages = (messages or []) + [{"role": "user", "content": user_msg}]

    if _openai_available():
        try:
            api_key = os.environ["OPENAI_API_KEY"]
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            sys_prompt = (
                "You are a helpful web assistant for a Flask app. "
                "Help users navigate pages and describe where to click. "
                f"Current page path: {path}. Keep answers concise."
            )
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": sys_prompt}] + messages[-20:],
                "temperature": 0.3,
            }
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "(No content)")
            )
            return jsonify({
                "reply": content,
                "provider": "openai",
                "model": model,
            })
        except Exception as e:
            # Fall back to offline if API fails
            return jsonify({
                "reply": f"[離線回覆] 無法連線至 LLM：{e}",
                "provider": "offline",
            }), 200

    # Offline fallback – provide basic help
    hint = (
        "我是離線導覽員。你可以：1) 上傳人物照 → /upload1，"
        "2) 上傳衣服 → /upload2，3) 到首頁查看最新輸出，或使用提示詞助手整理 prompt。"
    )
    return jsonify({
        "reply": hint,
        "provider": "offline",
    })

