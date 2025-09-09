# front_end_flask.py

import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from collections import OrderedDict

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------------
# 內網服務地址
# -----------------------------
TRANSLATE_SERVER = "http://172.24.11.4:5000"   # 如果有翻譯電腦(可選)，沒用到可刪
GENERATION_SERVER = "http://172.24.11.7:5005" # 生圖電腦

# 假設對外域名
EXTERNAL_API_URL = "https://pose.picturesmagician.com"

processing_requests = OrderedDict()

# -----------------------------
# (可選) 翻譯轉發
# -----------------------------
@app.route("/translate", methods=["POST"])
def translate():
    data = request.json
    user_id = data.get("user_id")
    text = data.get("text", "").strip()
    if not user_id or not text:
        return jsonify({"error": "缺少必要參數"}), 400

    if user_id in processing_requests:
        return jsonify({"error": "請求正在處理中"}), 429

    processing_requests[user_id] = True
    try:
        resp = requests.post(f"{TRANSLATE_SERVER}/translate",
                             json={"user_id": user_id, "text": text},
                             timeout=30)
        out = resp.json()
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        processing_requests.pop(user_id, None)

@app.route("/cancel/<user_id>", methods=["DELETE"])
def cancel_request(user_id):
    if user_id in processing_requests:
        processing_requests.pop(user_id, None)
        # 嘗試呼叫翻譯電腦的 cancel
        try:
            requests.delete(f"{TRANSLATE_SERVER}/cancel/{user_id}")
        except:
            pass
        return jsonify({"message": "已取消"})
    return jsonify({"error": "找不到此用戶的請求"}), 404

# -----------------------------
# 文生模式 - 轉發
# -----------------------------
@app.route("/pose_control_text", methods=["POST"])
def pose_control_text():
    """
    前端傳來: { prompt, cfg_scale, sampler, scheduler, seed, pose_image(可選) } 
    轉給生圖電腦 /pose_control_text
    """
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "缺少prompt"}), 400
    try:
        resp = requests.post(f"{GENERATION_SERVER}/pose_control_text",
                             json=data, timeout=300)
        result = resp.json()
        if "image_url" in result:
            # 若image_url是內網位址，替換成外網
            result["image_url"] = result["image_url"].replace(GENERATION_SERVER, EXTERNAL_API_URL)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# 圖生模式 - 轉發
# -----------------------------
@app.route("/pose_control_image", methods=["POST"])
def pose_control_image():
    """
    前端傳來: { prompt, image(base64), cfg_scale, sampler, scheduler, seed, pose_image(可選) }
    轉給生圖電腦 /pose_control_image
    """
    data = request.get_json()
    if not data or "prompt" not in data or "image" not in data:
        return jsonify({"error": "缺少參數"}), 400

    try:
        resp = requests.post(f"{GENERATION_SERVER}/pose_control_image",
                             json=data, timeout=300)
        result = resp.json()
        if "image_url" in result:
            result["image_url"] = result["image_url"].replace(GENERATION_SERVER, EXTERNAL_API_URL)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# 圖片代理 (可選)
# -----------------------------
@app.route("/get_image/<filename>", methods=["GET"])
def proxy_get_image(filename):
    """
    選擇策略：
    1) 直接代理到生圖電腦 
    2) or send_from_directory() (若已搬檔至前端電腦)
    這裡示範 "代理模式"。
    """
    try:
        fetch_url = f"{GENERATION_SERVER}/get_image/{filename}"
        r = requests.get(fetch_url, timeout=30)
        if r.status_code != 200:
            return jsonify({"error": "讀取檔案失敗"}), 404
        return r.content, r.status_code, {"Content-Type": r.headers.get("Content-Type", "image/png")}
    except Exception as e:
        return str(e), 500

# -----------------------------
# 啟動
# -----------------------------
if __name__ == "__main__":
    # 對外提供port
    app.run(host="0.0.0.0", port=5005, debug=False)
