from __future__ import annotations

import re
from typing import Dict, List

from flask import Blueprint, request, jsonify
from app.extensions import limiter, csrf


bp = Blueprint("prompt", __name__)
csrf.exempt(bp)


QUALITY_TOKENS = [
    "best quality",
    "masterpiece",
    "ultra-detailed",
    "highres",
]

NEGATIVE_DEFAULT = ", ".join([
    "lowres",
    "blurry",
    "worst quality",
    "bad anatomy",
    "bad hands",
    "extra digits",
    "missing fingers",
    "watermark",
    "logo",
    "text",
    "jpeg artifacts",
])

STYLE_PRESETS: Dict[str, Dict[str, List[str] | str]] = {
    "photoreal": {
        "name": "寫實攝影 Photoreal",
        "positive": [
            "photorealistic",
            "cinematic lighting",
            "shallow depth of field",
            "film grain",
            "skin texture",
            "sharp focus",
        ],
    },
    "anime": {
        "name": "二次元 Anime",
        "positive": [
            "anime style",
            "vibrant colors",
            "cel shading",
            "sharp lines",
            "highly detailed",
            "dynamic lighting",
        ],
    },
    "illustration": {
        "name": "插畫 Illustration",
        "positive": [
            "digital illustration",
            "soft shading",
            "concept art",
            "artstation trending",
            "volumetric lighting",
        ],
    },
    "studio": {
        "name": "棚拍 Studio",
        "positive": [
            "studio lighting",
            "softbox",
            "rim light",
            "key light",
            "clean background",
        ],
    },
}


def _normalize_prompt(text: str) -> str:
    text = text.replace("\n", ", ")
    text = re.sub(r"[、，；;]+", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Ensure trailing comma separation is tidy
    text = re.sub(r"\s*,\s*", ", ", text)
    return text


@bp.get("/prompt/presets")
def presets():
    return jsonify({
        "quality": QUALITY_TOKENS,
        "negative_default": NEGATIVE_DEFAULT,
        "styles": {k: {"name": v["name"], "positive": v["positive"]} for k, v in STYLE_PRESETS.items()},
    })


@bp.post("/prompt/expand")
@limiter.limit("60/minute")
def expand():
    data = request.get_json(silent=True) or {}
    src = (data.get("prompt") or request.form.get("prompt") or "").strip()
    style_key = (data.get("style") or request.form.get("style") or "").strip()
    include_quality = str(data.get("include_quality") or request.form.get("include_quality") or "1") in ("1", "true", "True")

    if not src:
        return jsonify(error="缺少 prompt"), 400

    # Build list
    parts: List[str] = []
    if include_quality:
        parts.extend(QUALITY_TOKENS)

    # Style
    preset = STYLE_PRESETS.get(style_key)
    if not preset:
        # simple inference
        lower = src.lower()
        if any(k in lower for k in ["anime", "二次元", "動漫", "manga"]):
            preset = STYLE_PRESETS["anime"]
        elif any(k in lower for k in ["photo", "寫實", "realistic", "photograph"]):
            preset = STYLE_PRESETS["photoreal"]
    if preset:
        parts.extend(preset["positive"])  # type: ignore[index]

    parts.append(src)

    out = _normalize_prompt(", ".join(parts))
    return jsonify({
        "prompt": out,
        "negative_suggestion": NEGATIVE_DEFAULT,
        "applied_style": style_key or (preset and next((k for k, v in STYLE_PRESETS.items() if v is preset), "")) or "",
    })

