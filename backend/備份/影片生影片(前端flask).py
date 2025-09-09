import base64
import json
import os
import time
import uuid
import threading
import urllib.request
import urllib.error
import urllib.parse
import requests
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from collections import OrderedDict

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
    methods=["GET", "POST", "OPTIONS", "DELETE"]
)

# 讓 Flask 正確處理反向代理 (如 Cloudflare Tunnel) 傳來的標頭
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ------------------------------------------------------
# 內網服務地址 (請根據實際環境修改)
# ------------------------------------------------------
TRANSLATE_SERVER = "http://172.24.11.4:5000"         # 翻譯服務（共用）
BACKEND_VIDEO2VIDEO_SERVER = "http://172.24.11.7:5000" # 影片生影片後端服務（生影片電腦）

# 對外提供的 HTTPS 網域（例如透過 Cloudflare Tunnel 之類）
VIDEO_BASE_URL = "https://api.picturesmagician.com"

# 新增：生成影片檔案目標資料夾（該目標資料夾必須能由前端機器存取）
TARGET_DIR = "D:/sd1.5_animediff_video2video_dataset/"

# 用於排隊或取消翻譯請求
processing_requests = OrderedDict()

# ========================================================
# (1) 翻譯路由 (共用翻譯服務)
# ========================================================
@app.route("/translate", methods=["POST"])
def translate():
    data = request.json
    user_id = data.get("user_id")
    text = data.get("text", "").strip()
    if not text or not user_id:
        return jsonify({"error": "請求缺少必要參數"}), 400

    if user_id in processing_requests:
        return jsonify({"error": "請求正在處理中，請稍後"}), 429
    processing_requests[user_id] = True

    try:
        resp = requests.post(
            f"{TRANSLATE_SERVER}/translate",
            json={"text": text, "user_id": user_id},
            timeout=30
        )
        resp_json = resp.json()
        translated_text = resp_json.get("translatedText", "翻譯失敗")
        return jsonify({
            "translatedText": translated_text,
            "queueNumber": list(processing_requests.keys()).index(user_id) + 1
        })
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"翻譯服務無回應: {e}"}), 500
    finally:
        processing_requests.pop(user_id, None)

@app.route("/cancel/<user_id>", methods=["DELETE"])
def cancel_request(user_id):
    if user_id in processing_requests:
        processing_requests.pop(user_id, None)
        try:
            requests.delete(f"{TRANSLATE_SERVER}/cancel/{user_id}")
        except requests.exceptions.RequestException:
            pass
        return jsonify({"message": "請求已取消"})
    return jsonify({"error": "找不到此用戶的請求"}), 404

# ========================================================
# (2) 影片上傳路由（影片生影片專用）
# ========================================================
@app.route("/upload_video", methods=["POST"])
def upload_video():
    """
    上傳影片檔案，並回傳對外影片 URL
    """
    video = request.files.get("video")
    if not video:
        return jsonify({"error": "請上傳影片"}), 400
    upload_dir = os.path.join(os.getcwd(), "uploaded_videos")
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(f"{uuid.uuid4().hex}_{video.filename}")
    file_path = os.path.join(upload_dir, filename)
    video.save(file_path)
    video_url = f"{VIDEO_BASE_URL}/get_video/{filename}"
    return jsonify({"video_url": video_url})

# ========================================================
# (3) 影片代理路由：先嘗試從本機讀取，找不到則代理後端服務
# ========================================================
@app.route("/get_video/<path:filename>", methods=["GET"])
def get_video(filename):
    """
    代理影片檔案請求，讓瀏覽器可透過 VIDEO_BASE_URL 取得影片檔案。
    若本機 uploaded_videos 中找不到，則代理請求後端影片服務。
    """
    upload_dir = os.path.join(os.getcwd(), "uploaded_videos")
    file_path = os.path.join(upload_dir, filename)
    if os.path.exists(file_path):
        response = send_from_directory(upload_dir, filename)
    else:
        try:
            url = f"{BACKEND_VIDEO2VIDEO_SERVER}/get_video/{filename}"
            r = requests.get(url, stream=True)
            if r.status_code == 200:
                response = Response(r.content, mimetype=r.headers.get('Content-Type', 'video/mp4'))
            else:
                return jsonify({"error": "影片不存在或無法取得"}), r.status_code
        except requests.exceptions.RequestException as e:
            return jsonify({"error": f"後端影片服務無回應: {str(e)}"}), 500
    response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# ========================================================
# (4) 影片生影片生成 SSE 路由（GET，採用 SSE pass-through）
# ========================================================
@app.route("/generate_video2video_stream", methods=["GET"])
def generate_video2video_stream():
    """
    接收前端傳來的影片生影片請求（提示詞、影片 URL、種子等皆由查詢字串提供），
    下載影片後暫存，再以 requests 的 stream 模式呼叫後端 (生影片電腦) 的 /generate_video2video，
    並以 SSE 方式逐步回傳進度更新，最終回傳影片對外 URL。
    """
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"error": "請提供有效的提示詞"}), 400

    try:
        seed = int(request.args.get("seed", 0))
    except ValueError:
        seed = 0
    if seed == 0:
        seed = int(time.time() * 1000) % 1000000

    # 取得影片 URL（非 Base64）
    video_url = request.args.get("video")
    if not video_url:
        return jsonify({"error": "請上傳影片"}), 400

    # 下載影片
    try:
        resp = requests.get(video_url, timeout=30)
        if resp.status_code != 200:
            return jsonify({"error": "下載影片失敗"}), 400
        video_bytes = resp.content
    except Exception as e:
        return jsonify({"error": "下載影片錯誤: " + str(e)}), 400

    # 暫存影片到本機 temp_uploads 資料夾
    temp_path = os.path.join(os.getcwd(), "temp_uploads")
    os.makedirs(temp_path, exist_ok=True)
    temp_filename = secure_filename(f"{uuid.uuid4().hex}.mp4")
    file_path = os.path.join(temp_path, temp_filename)
    with open(file_path, "wb") as f:
        f.write(video_bytes)
    print(f"✅ [前端] 下載影片並儲存於 {file_path}")

    def sse_stream():
        with open(file_path, "rb") as f:
            files = {"video": (temp_filename, f, "video/mp4")}
            data = {
                "text": text,
                "seed": seed
            }
            with requests.post(
                f"{BACKEND_VIDEO2VIDEO_SERVER}/generate_video2video",
                data=data,
                files=files,
                timeout=1800,
                stream=True
            ) as r:
                for line in r.iter_lines(decode_unicode=True):
                    if line is not None:
                        yield line + "\n"
        try:
            os.remove(file_path)
        except Exception as e2:
            print("刪除暫存檔失敗：", e2)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return Response(sse_stream(), headers=headers, mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
