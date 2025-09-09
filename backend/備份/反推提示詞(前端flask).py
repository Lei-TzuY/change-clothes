import os
import json
import requests
from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------------
# 內網生圖服務地址（圖像反推提示詞後端服務器）
# -----------------------------
GENERATION_SERVER = "http://172.24.11.7:5007"  # 請根據實際環境修改

# 對外提供的域名（例如透過 Cloudflare Tunnel 提供的 HTTPS 網域）
EXTERNAL_API_URL = "https://reverseprompt.picturesmagician.com"

# -----------------------------
# 圖像反推提示詞 – 前端轉發接口
# -----------------------------
@app.route("/reverse_prompt", methods=["POST"])
def reverse_prompt():
    """
    前端傳來的 JSON 格式（例如）：
    {
      "image": "data:image/png;base64,xxxx..."   // 必填，上傳的圖片 (base64格式)
      // 其他可選參數依後端工作流程需求傳入
    }
    此接口將請求轉發至內網圖像反推提示詞後端服務，
    並將回傳的文本檔 URL 中的內網地址替換為對外域名，再回傳給前端。
    """
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "缺少圖片資料"}), 400
    try:
        resp = requests.post(f"{GENERATION_SERVER}/reverse_prompt", json=data, timeout=300)
        result = resp.json()
        # 假設後端返回的關鍵鍵為 "text_url"
        if "text_url" in result:
            result["text_url"] = result["text_url"].replace(GENERATION_SERVER, EXTERNAL_API_URL)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# 文本檔案代理接口 - 修改為 /get_image 路由
# -----------------------------
@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    """
    代理模式：將對 /get_image/<filename> 的請求轉發到內網服務器，
    以便前端透過 HTTPS 取得生成的文本檔（提示詞）。
    """
    try:
        fetch_url = f"{GENERATION_SERVER}/get_image/{filename}"
        r = requests.get(fetch_url, timeout=30)
        if r.status_code != 200:
            return jsonify({"error": "讀取檔案失敗"}), 404
        response = make_response(r.content, r.status_code)
        response.headers["Content-Type"] = r.headers.get("Content-Type", "text/plain")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# 啟動 Flask 服務
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5007, debug=False)
