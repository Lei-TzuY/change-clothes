from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import requests
from collections import OrderedDict
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# 允許 CORS：測試階段允許所有網域；上線建議只允許特定網域
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
# 內網後端服務地址 (請依實際環境修改)
# -----------------------------
TRANSLATE_SERVER = "http://172.24.11.4:5000"  # 翻譯服務
BACKEND_SERVER   = "http://172.24.11.7:5000"  # 生圖服務

# -----------------------------
# Cloudflare Tunnel 提供的 HTTPS 網域
# (讓前端取得圖片時使用 HTTPS，避免 Mixed Content)
# -----------------------------
IMAGE_BASE_URL = "https://api.picturesmagician.com"

# 用來追蹤翻譯請求的處理狀態
processing_requests = OrderedDict()

# =========================================================
# 1) 翻譯路由
# =========================================================
@app.route("/translate", methods=["POST"])
def translate():
    """
    代理翻譯請求到內網翻譯機器
    """
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

# =========================================================
# 2) 取消翻譯路由
# =========================================================
@app.route("/cancel/<user_id>", methods=["DELETE"])
def cancel_request(user_id):
    """
    取消翻譯請求
    """
    if user_id in processing_requests:
        processing_requests.pop(user_id, None)
        try:
            requests.delete(f"{TRANSLATE_SERVER}/cancel/{user_id}")
        except requests.exceptions.RequestException:
            pass
        return jsonify({"message": "請求已取消"})
    return jsonify({"error": "找不到此用戶的請求"}), 404

# =========================================================
# 3) 生圖路由
# =========================================================
@app.route("/generate_image", methods=["POST"])
def generate_image():
    """
    將前端請求代理到內網生圖服務，並將後端返回的 HTTP 圖片網址
    替換成 HTTPS (api.picturesmagician.com)，避免 Mixed Content。
    """
    data = request.json
    print("Proxy 收到的 JSON:", data)
    try:
        # 將請求轉發到生圖機器
        resp = requests.post(f"{BACKEND_SERVER}/generate_image", json=data, timeout=60)
        resp_json = resp.json()
        print("後端返回的 JSON:", resp_json)

        if "image_url" in resp_json:
            # 後端回傳的 URL 可能是 http://172.24.11.7:5000/get_image/xxx.png
            # 在這裡把 "http://172.24.11.7:5000" 替換為 "https://api.picturesmagician.com"
            old_url = resp_json["image_url"]
            new_url = old_url.replace("http://172.24.11.7:5000", IMAGE_BASE_URL)
            return jsonify({"image_url": new_url})
        else:
            return jsonify({"error": "生成圖片失敗"}), 500
    except requests.exceptions.RequestException as e:
        print("❌ 轉發請求錯誤:", str(e))
        return jsonify({"error": f"生圖服務無回應: {str(e)}"}), 500

# =========================================================
# 4) 取圖路由
# =========================================================
@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    """
    將對 /get_image/<filename> 的請求再代理到內網生圖機器，
    讓使用者能透過 https://api.picturesmagician.com/get_image/... 取得圖片。
    """
    print(f"Proxy 收到 get_image 請求: {filename}")
    try:
        # 重新代理到內網生圖機器
        url = f"{BACKEND_SERVER}/get_image/{filename}"
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            # 將後端回傳的檔案內容以流的方式回傳
            return Response(r.content, mimetype=r.headers.get('Content-Type', 'image/png'))
        else:
            print(f"後端生圖機器回傳 {r.status_code}，無法取得圖片")
            return jsonify({"error": "圖片不存在或無法取得"}), r.status_code
    except requests.exceptions.RequestException as e:
        print("❌ get_image 代理錯誤:", str(e))
        return jsonify({"error": f"生圖機器無回應: {str(e)}"}), 500

# =========================================================
# 主程式入口
# =========================================================
if __name__ == "__main__":
    # 監聽 0.0.0.0:5000，讓 Cloudflare Tunnel 代理到此服務
    app.run(host="0.0.0.0", port=5000, debug=False)
