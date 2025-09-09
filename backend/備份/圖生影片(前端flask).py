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
TRANSLATE_SERVER = "http://172.24.11.4:5000"       # 翻譯服務（共用）
BACKEND_IMG2VIDEO_SERVER = "http://172.24.11.7:5000"  # 圖生影片後端服務（生影片電腦）

# 對外提供的 HTTPS 網域（例如透過 Cloudflare Tunnel 之類）
VIDEO_BASE_URL = "https://api.picturesmagician.com"

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

    # 防止重複請求
    if user_id in processing_requests:
        return jsonify({"error": "請求正在處理中，請稍後"}), 429
    processing_requests[user_id] = True

    try:
        # 將翻譯請求代理至內網 TRANSLATE_SERVER
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
    """
    用於取消翻譯的排隊請求
    """
    if user_id in processing_requests:
        processing_requests.pop(user_id, None)
        try:
            # 也向 TRANSLATE_SERVER 發出取消
            requests.delete(f"{TRANSLATE_SERVER}/cancel/{user_id}")
        except requests.exceptions.RequestException:
            pass
        return jsonify({"message": "請求已取消"})
    return jsonify({"error": "找不到此用戶的請求"}), 404

# ========================================================
# (2) 圖生影片圖片上傳端點（新增）
# ========================================================
@app.route("/upload_image", methods=["POST"])
def upload_image():
    """
    單獨上傳圖片，並回傳對外圖片 URL
    """
    image = request.files.get("image")
    if not image:
        return jsonify({"error": "請上傳圖片"}), 400
    upload_dir = os.path.join(os.getcwd(), "uploaded_images")
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(f"{uuid.uuid4().hex}_{image.filename}")
    file_path = os.path.join(upload_dir, filename)
    image.save(file_path)
    # 假設 /get_image 提供圖片下載，對外 URL 為 VIDEO_BASE_URL + /get_image/<filename>
    image_url = f"{VIDEO_BASE_URL}/get_image/{filename}"
    return jsonify({"image_url": image_url})

@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    """
    提供上傳圖片的下載/顯示
    """
    upload_dir = os.path.join(os.getcwd(), "uploaded_images")
    if not os.path.exists(os.path.join(upload_dir, filename)):
        return jsonify({"error": "檔案不存在"}), 404
    return send_from_directory(upload_dir, filename)

# ========================================================
# (3) 圖生影片生成 SSE 路由（GET，採用 SSE pass-through）
# ========================================================
@app.route("/generate_img2video_stream", methods=["GET"])
def generate_img2video_stream():
    """
    接收前端傳來的圖生影片請求（文字、圖片 URL、參數皆由查詢字串提供），
    下載圖片後暫存，再以 requests 的 stream 模式呼叫後端 (生影片電腦) 的 /generate_img2video，
    並以 SSE 方式逐步回傳進度更新，最終回傳影片對外 URL。
    """
    # 取得文字與參數（皆由查詢字串傳入）
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"error": "請提供有效的提示詞"}), 400

    try:
        duration = int(request.args.get("duration", 4))
    except ValueError:
        duration = 4

    try:
        frame_rate = int(request.args.get("frame_rate", 8))
    except ValueError:
        frame_rate = 8

    try:
        seed = int(request.args.get("seed", 0))
    except ValueError:
        seed = 0
    if seed == 0:
        seed = int(time.time() * 1000) % 1000000

    # 取得圖片 URL（非 Base64）
    image_url = request.args.get("image")
    if not image_url:
        return jsonify({"error": "請上傳圖片"}), 400

    # 下載圖片
    try:
        resp = requests.get(image_url, timeout=30)
        if resp.status_code != 200:
            return jsonify({"error": "下載圖片失敗"}), 400
        image_bytes = resp.content
    except Exception as e:
        return jsonify({"error": "下載圖片錯誤: " + str(e)}), 400

    # 暫存圖片到本機 temp_uploads 資料夾
    temp_path = os.path.join(os.getcwd(), "temp_uploads")
    os.makedirs(temp_path, exist_ok=True)
    temp_filename = secure_filename(f"{uuid.uuid4().hex}.png")
    file_path = os.path.join(temp_path, temp_filename)
    with open(file_path, "wb") as f:
        f.write(image_bytes)
    print(f"✅ [前端] 下載圖片並儲存於 {file_path}")

    def sse_stream():
        # 直接 pass-through 後端 SSE 資料，不做額外處理
        with open(file_path, "rb") as f:
            files = {"image": (temp_filename, f, "image/png")}
            data = {
                "text": text,
                "duration": duration,
                "frame_rate": frame_rate,
                "seed": seed
            }
            with requests.post(
                f"{BACKEND_IMG2VIDEO_SERVER}/generate_img2video",
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
        "X-Accel-Buffering": "no"  # 禁用反向代理緩衝 (例如 Nginx)
    }
    return Response(sse_stream(), headers=headers, mimetype="text/event-stream")

# ========================================================
# 新增: 代理影片檔案路由
# ========================================================
@app.route("/get_video/<path:filename>", methods=["GET"])
def get_video(filename):
    """
    代理後端影片檔案請求，讓瀏覽器可透過 VIDEO_BASE_URL 域名取得影片檔案
    """
    # 這裡我們將請求轉發給後端圖生影片服務的 /get_video 路由
    url = f"{BACKEND_IMG2VIDEO_SERVER}/get_video/{filename}"
    try:
        r = requests.get(url, stream=True)
        if r.status_code != 200:
            return jsonify({"error": "影片不存在或無法取得"}), r.status_code
        return Response(r.content, mimetype=r.headers.get('Content-Type', 'video/mp4'))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # 前端 Flask 監聽 0.0.0.0:5000
    app.run(host="0.0.0.0", port=5000, debug=False)
