import os
import time
import threading
import base64
from collections import OrderedDict

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------
# 基本設定與後端伺服器地址
# -----------------------
# 存放用的目錄（依需求修改）
SAVE_DIR = r"C:\Users\Public\partial_repaint"
os.makedirs(SAVE_DIR, exist_ok=True)

# 後端服務地址（內網地址）
TRANSLATE_SERVER = "http://172.24.11.4:5000"   # 翻譯服務（部署於 172.24.11.4）
GENERATION_SERVER = "http://172.24.11.7:5002"    # 局部重繪生图服务（部署於 172.24.11.7）

# 外網對外提供的域名（Cloudflare Tunnel 提供的 HTTPS 網域）
EXTERNAL_API_URL = "https://inpant.picturesmagician.com"

# 使用 OrderedDict 管理翻譯請求（保持請求順序）
processing_requests = OrderedDict()

# -----------------------
# 翻譯相關 API（转发至 172.24.11.4）
# -----------------------
@app.route("/translate", methods=["POST"])
def translate():
    data = request.json
    user_id = data.get("user_id")
    text = data.get("text", "").strip()
    if not text or not user_id:
        return jsonify({"error": "缺少必要參數"}), 400
    if user_id in processing_requests:
        return jsonify({"error": "請求正在處理中，請稍後"}), 429
    processing_requests[user_id] = True
    try:
        resp = requests.post(f"{TRANSLATE_SERVER}/translate",
                             json={"text": text, "user_id": user_id},
                             timeout=30)
        translated_text = resp.json().get("translatedText", "翻譯失敗")
        return jsonify({
            "translatedText": translated_text,
            "queueNumber": list(processing_requests.keys()).index(user_id) + 1
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        processing_requests.pop(user_id, None)

@app.route("/cancel/<user_id>", methods=["DELETE"])
def cancel_request(user_id):
    if user_id in processing_requests:
        processing_requests.pop(user_id, None)
        try:
            requests.delete(f"{TRANSLATE_SERVER}/cancel/{user_id}")
        except Exception:
            pass
        return jsonify({"message": "請求已取消"})
    return jsonify({"error": "找不到此用戶的請求"}), 404

# -----------------------
# 局部重繪生图转发 API（转发至 172.24.11.7）
# -----------------------
@app.route("/convert-image", methods=["POST"])
def convert_image():
    json_data = request.get_json()
    if not json_data:
        return jsonify({"error": "無效的 JSON 請求"}), 400
    try:
        resp = requests.post(f"{GENERATION_SERVER}/convert-image",
                             json=json_data,
                             timeout=180)
        result = resp.json()
        # 若回傳中有圖片 URL，將內網地址替換為外網域名
        if "image_url" in result:
            result["image_url"] = result["image_url"].replace(GENERATION_SERVER, EXTERNAL_API_URL)
        if "pure_painting_url" in result and result["pure_painting_url"]:
            result["pure_painting_url"] = result["pure_painting_url"].replace(GENERATION_SERVER, EXTERNAL_API_URL)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_image/<filename>", methods=["GET"])
def proxy_get_image(filename):
    try:
        resp = requests.get(f"{GENERATION_SERVER}/get_image/{filename}")
        return resp.content, resp.status_code, resp.headers.items()
    except Exception as e:
        return str(e), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
