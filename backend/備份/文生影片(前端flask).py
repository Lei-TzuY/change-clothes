from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import requests
import time
import threading
import json
from collections import OrderedDict
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
    methods=["GET", "POST", "OPTIONS", "DELETE"]
)
# 讓 Flask 正確處理 Cloudflare Tunnel 傳來的標頭
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# -----------------------------
# 內網服務地址 (請根據實際環境修改)
# -----------------------------
TRANSLATE_SERVER = "http://172.24.11.4:5000"      # 翻譯服務（共用，不再設計）
BACKEND_VIDEO_SERVER = "http://172.24.11.7:5000"    # 影片生圖服務（後端生影片）
# -----------------------------
# 對外提供的 HTTPS 網域（例如 Cloudflare Tunnel 提供的網域）
# -----------------------------
VIDEO_BASE_URL = "https://api.picturesmagician.com"

# 用來追蹤翻譯請求的處理狀態
processing_requests = OrderedDict()

# ========================================================
# 1) 翻譯路由 (共用翻譯服務)
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
# 2) 影片生成同步路由 (原有方式)
# ========================================================
@app.route("/generate_video", methods=["POST"])
def generate_video():
    """
    將前端傳來的影片生成請求代理到內網影片生圖服務，
    並將後端返回的影片 URL 中內網地址替換為對外 HTTPS 網域。
    """
    data = request.json
    try:
        # 將 timeout 參數從 120 秒調整為 1800 秒 (30 分鐘)
        resp = requests.post(f"{BACKEND_VIDEO_SERVER}/generate_video", json=data, timeout=1800)
        resp_json = resp.json()
        if "video_url" in resp_json:
            # 後端回傳的 URL 可能為 http://172.24.11.7:5000/get_video/xxx.mp4
            old_url = resp_json["video_url"]
            new_url = old_url.replace("http://172.24.11.7:5000", VIDEO_BASE_URL)
            return jsonify({"video_url": new_url})
        else:
            return jsonify({"error": "生成影片失敗"}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"生影片服務無回應: {str(e)}"}), 500

# ========================================================
# 3) 影片生成 SSE 路由
# ========================================================
@app.route("/generate_video_stream", methods=["GET"])
def generate_video_stream():
    """
    利用 SSE 傳送影片生成進度更新：
    前端透過 query string 傳入 text、duration、frame_rate 與 seed，
    後端在背景呼叫影片生成服務，並持續回傳進度更新，
    最後回傳影片 URL 或錯誤訊息。
    """
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"error": "缺少描述文字參數"}), 400
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

    requestData = {
        "text": text,
        "duration": duration,
        "frame_rate": frame_rate,
        "batch_size": duration * frame_rate,
        "seed": seed
    }

    result = {}

    def call_backend():
        try:
            resp = requests.post(f"{BACKEND_VIDEO_SERVER}/generate_video", json=requestData, timeout=1800)
            resp_json = resp.json()
            if "video_url" in resp_json:
                old_url = resp_json["video_url"]
                new_url = old_url.replace("http://172.24.11.7:5000", VIDEO_BASE_URL)
                result["video_url"] = new_url
            else:
                result["error"] = "生成影片失敗"
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=call_backend)
    thread.start()

    def event_stream():
        progress = 0
        # 每60秒傳送一次進度更新，進度最多累加到90%
        while thread.is_alive():
            update = {"progress": progress, "message": "影片生成中..."}
            yield f"data: {json.dumps(update)}\n\n"
            time.sleep(60)
            progress = min(progress + 10, 90)
        thread.join()
        # 當背景執行緒完成後，回傳最終結果
        if "video_url" in result:
            final_update = {"progress": 100, "video_url": result["video_url"], "message": "影片生成完成！"}
            yield f"data: {json.dumps(final_update)}\n\n"
        else:
            final_update = {"progress": 100, "error": result.get("error", "未知錯誤"), "message": "影片生成失敗"}
            yield f"data: {json.dumps(final_update)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")

# ========================================================
# 4) 影片取回路由
# ========================================================
@app.route("/get_video/<path:filename>", methods=["GET"])
def get_video(filename):
    """
    將對 /get_video/<filename> 的請求代理到內網影片生圖服務，
    讓使用者透過 HTTPS 取得影片檔案。
    """
    try:
        url = f"{BACKEND_VIDEO_SERVER}/get_video/{filename}"
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            return Response(r.content, mimetype=r.headers.get('Content-Type', 'video/mp4'))
        else:
            return jsonify({"error": "影片不存在或無法取得"}), r.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"生影片服務無回應: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
