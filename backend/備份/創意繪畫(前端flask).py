import os
import time
import threading
import base64
import io
from collections import OrderedDict

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------
# 基本設定與後端伺服器地址
# -----------------------
SAVE_DIR = r"C:\Users\Public\字串傳送"
os.makedirs(SAVE_DIR, exist_ok=True)

# 內網服務地址
TRANSLATE_SERVER = "http://172.24.11.4:5000"   # 翻譯服務
BACKEND_SERVER = "http://172.24.11.7:5003"       # 創意繪畫生成服務

# 外網對外提供的域名（例如 Cloudflare Tunnel 提供的 HTTPS 網域）
EXTERNAL_API_URL = "https://draw.picturesmagician.com"

processing_requests = OrderedDict()

# -----------------------
# 翻譯相關 API
# -----------------------
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
        response = requests.post(
            f"{TRANSLATE_SERVER}/translate",
            json={"text": text, "user_id": user_id},
            timeout=30
        )
        translated_text = response.json().get("translatedText", "翻譯失敗")
        return jsonify({
            "translatedText": translated_text,
            "queueNumber": list(processing_requests.keys()).index(user_id) + 1
        })
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"後端無回應: {e}"}), 500
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

# -----------------------
# 創意繪畫生成 API（轉發至後端服務）
# -----------------------
@app.route("/convert-image", methods=["POST"])
def convert_image():
    # 使用 force=True 以確保解析 JSON（避免 Content-Type 問題）
    data = request.get_json(force=True)
    if not data or "image" not in data:
        return jsonify({"error": "未提供圖像資料"}), 400

    # 此端點直接將接收到的 JSON 轉發給後端生成服務
    try:
        resp = requests.post(f"{BACKEND_SERVER}/convert-image", json=data, timeout=120)
        result = resp.json()
        # 若回傳中已有圖片 URL，可在此進行替換（若後端未替換則此處可補充）
        if "image_url" in result:
            # 此處不一定需要替換，因為後端生成會用本機 host_url；也可改為外網域名：
            result["image_url"] = EXTERNAL_API_URL + "/get_image/" + result["image_url"].split("/")[-1] + f"?t={int(time.time())}"
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_image/<filename>", methods=["GET"])
def proxy_get_image(filename):
    try:
        resp = requests.get(f"{BACKEND_SERVER}/get_image/{filename}")
        return resp.content, resp.status_code, resp.headers.items()
    except Exception as e:
        return str(e), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
