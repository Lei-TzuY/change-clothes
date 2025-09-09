import os
import time
import threading
import base64
import io
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
SAVE_DIR = r"C:\Users\Public\字串傳送"
os.makedirs(SAVE_DIR, exist_ok=True)

# 後端服務地址（內網地址）
TRANSLATE_SERVER = "http://172.24.11.4:5000"   # 翻譯服務
BACKEND_SERVER = "http://172.24.11.7:5001"       # 圖生圖後端服務

# 外網對外提供的域名（Cloudflare Tunnel 提供的 HTTPS 網域）
IMAGE_BASE_URL = "https://image.picturesmagician.com"

# 使用 OrderedDict 管理翻譯請求（保持請求順序）
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

    # 若同一個 user_id 已在處理中則回傳錯誤
    if user_id in processing_requests:
        return jsonify({"error": "請求正在處理中，請稍後"}), 429

    # 加入請求佇列
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
            # 同時通知翻譯後端取消該請求
            requests.delete(f"{TRANSLATE_SERVER}/cancel/{user_id}")
        except requests.exceptions.RequestException:
            pass
        return jsonify({"message": "請求已取消"})
    return jsonify({"error": "找不到此用戶的請求"}), 404

# -----------------------
# 圖生圖相關 API
# -----------------------
@app.route("/convert-image", methods=["POST"])
def convert_image():
    json_data = request.get_json()
    if not json_data:
        return jsonify({"error": "Invalid JSON"}), 400

    image_data = json_data.get("image")
    cfgScale = json_data.get("cfgScale", "7")
    samplerName = json_data.get("samplerName", "euler")
    scheduler = json_data.get("scheduler", "karras")
    seed = json_data.get("seed", "")
    
    if not image_data:
        return jsonify({"error": "No image provided"}), 400

    try:
        header, encoded = image_data.split(",", 1)
    except Exception as e:
        return jsonify({"error": "Invalid image data format", "details": str(e)}), 400

    file_ext = "png"
    if "jpeg" in header or "jpg" in header:
        file_ext = "jpg"
    try:
        file_bytes = base64.b64decode(encoded)
    except Exception as e:
        return jsonify({"error": "Base64 decode error", "details": str(e)}), 400

    file_obj = io.BytesIO(file_bytes)
    file_obj.name = f"upload.{file_ext}"

    form_data = {
        "cfgScale": cfgScale,
        "samplerName": samplerName,
        "scheduler": scheduler,
        "seed": seed,
        # 此外可加入其他參數，如提示詞等
        "prompt": json_data.get("prompt", "")
    }
    files = {
        "image": (file_obj.name, file_obj, f"image/{file_ext}")
    }

    try:
        resp = requests.post(f"{BACKEND_SERVER}/image_to_image", data=form_data, files=files, timeout=120)
        resp_json = resp.json()
        # 若回傳中有圖片 URL，將內網地址替換為外網域名
        if "image_url" in resp_json:
            resp_json["image_url"] = resp_json["image_url"].replace(BACKEND_SERVER, IMAGE_BASE_URL)
        return jsonify(resp_json)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_image/<filename>", methods=["GET"])
def proxy_get_image(filename):
    try:
        resp = requests.get(f"{BACKEND_SERVER}/get_image/{filename}")
        return resp.content, resp.status_code, resp.headers.items()
    except Exception as e:
        return str(e), 500

# -----------------------
# 啟動 Flask 伺服器
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
