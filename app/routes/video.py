import os
import time
import uuid
from typing import Tuple

import numpy as np
from PIL import Image
from moviepy.editor import VideoClip
from flask import Blueprint, request, jsonify, current_app, url_for
from app.extensions import csrf, limiter
from config import OUTPUT_DIR, UPLOAD1


bp = Blueprint("video", __name__)
csrf.exempt(bp)


def _save_upload(file_storage, target_dir: str) -> str:
    os.makedirs(target_dir, exist_ok=True)
    _, ext = os.path.splitext(file_storage.filename or "")
    if not ext:
        ext = ".png"
    fn = f"{int(time.time())}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(target_dir, fn)
    file_storage.save(path)
    return path


def _pick_output_size(w: int, h: int, prefer: Tuple[int, int] | None) -> Tuple[int, int]:
    if prefer and prefer[0] and prefer[1]:
        return int(prefer[0]), int(prefer[1])
    # Keep aspect, cap long side to 720
    long = 720
    if w >= h:
        ow = long
        oh = int(h * (long / w))
    else:
        oh = long
        ow = int(w * (long / h))
    # Ensure multiples of 2 for h264
    ow += ow % 2
    oh += oh % 2
    return ow, oh


@bp.post("/img2vid")
@limiter.limit("20/minute")
def img2vid():
    if "image" not in request.files:
        return jsonify(error="請以 multipart/form-data 上傳 image 檔"), 400

    src_path = _save_upload(request.files["image"], UPLOAD1)

    # Parameters
    try:
        duration = float(request.form.get("duration", "4"))
    except Exception:
        duration = 4.0
    try:
        fps = int(request.form.get("fps", "24"))
    except Exception:
        fps = 24
    motion = (request.form.get("motion") or "zoom_in").strip()
    out_w = request.form.get("width")
    out_h = request.form.get("height")
    try:
        prefer_size = (int(out_w), int(out_h)) if out_w and out_h else None
    except Exception:
        prefer_size = None

    # Load image
    im = Image.open(src_path).convert("RGB")
    W, H = im.size
    OW, OH = _pick_output_size(W, H, prefer_size)

    # Precompute numpy array for speed
    # We'll crop on PIL per frame to preserve quality

    # Motion parameters
    start_zoom = 1.0
    end_zoom = 1.08 if motion == "zoom_in" else (0.92 if motion == "zoom_out" else 1.0)
    pan_x = {"pan_left": -0.2, "pan_right": 0.2}.get(motion, 0.0)
    pan_y = {"pan_up": -0.15, "pan_down": 0.15}.get(motion, 0.0)

    def make_frame(t: float):
        p = 0.0 if duration <= 0 else max(0.0, min(1.0, t / duration))
        zoom = start_zoom + (end_zoom - start_zoom) * p
        # Compute crop window under zoom + pan
        crop_w = int(W / zoom)
        crop_h = int(H / zoom)
        max_x = max(0, W - crop_w)
        max_y = max(0, H - crop_h)
        x = int((max_x / 2) + max_x * pan_x * (p - 0.5) * 2)
        y = int((max_y / 2) + max_y * pan_y * (p - 0.5) * 2)
        x = max(0, min(W - crop_w, x))
        y = max(0, min(H - crop_h, y))
        frame = im.crop((x, y, x + crop_w, y + crop_h)).resize((OW, OH), Image.LANCZOS)
        return np.asarray(frame)

    clip = VideoClip(make_frame, duration=max(0.5, duration))

    # Write video
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    out_fn = f"i2v_{ts}.mp4"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, out_fn)
    clip.write_videofile(
        out_path,
        fps=fps,
        codec="libx264",
        audio=False,
        preset="medium",
        ffmpeg_params=["-pix_fmt", "yuv420p"],
        verbose=False,
        logger=None,
    )

    url = url_for("main.serve_output", filename=out_fn)
    return jsonify(message="已產生影片", download=url, filename=out_fn, width=OW, height=OH, fps=fps, duration=duration), 200

