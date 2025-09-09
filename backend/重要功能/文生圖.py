import json
import os
import shutil
import time
import uuid
import urllib.request
from urllib.error import HTTPError

import websocket  # 請先安裝：pip install websocket-client
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from collections import OrderedDict
from werkzeug.middleware.proxy_fix import ProxyFix

# ← 新增這行
from config import (
    COMFYUI_API_URL,
    COMFYUI_OUTPUT_DIR,
    TARGET_DIR,
    EXTERNAL_URL,
    ALLOWED_ORIGINS
)

app = Flask(__name__)

# -------------------------------------------------------------------
# CORS 設定：開發階段允許所有網域；正式上線時請改為限制特定網域
# -------------------------------------------------------------------
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization",
                   "X-Requested-With", "Accept", "Origin"],
    methods=["GET", "POST", "OPTIONS", "DELETE"]
)

# -------------------------------------------------------------------
# ProxyFix：確保 Flask 能正確讀取 Cloudflare Tunnel 傳來的標頭
# -------------------------------------------------------------------
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# -------------------------------------------------------------------
# 內網後端服務地址：翻譯服務及生圖服務（請根據實際環境調整）
# -------------------------------------------------------------------
TRANSLATE_SERVER = "http://172.24.11.4:5000"
BACKEND_SERVER = "http://172.24.11.7:5000"

# -------------------------------------------------------------------
# Cloudflare Tunnel 對外提供的 HTTPS 網域（必須設定為 HTTPS）
# -------------------------------------------------------------------
IMAGE_BASE_URL = "https://api.picturesmagician.com"

# -------------------------------------------------------------------
# ComfyUI 輸出資料夾及目標資料夾（搬移檔案到此目標資料夾後供 /get_image 讀取）
# -------------------------------------------------------------------
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir = r"D:\大模型文生圖"
os.makedirs(target_dir, exist_ok=True)

# -------------------------------------------------------------------
# 用來追蹤翻譯請求狀態的 OrderedDict
# -------------------------------------------------------------------
processing_requests = OrderedDict()


# =============================
# 與 ComfyUI 溝通的函式
# =============================

# 確保這個 client_id 要能讓 WebSocket 連線使用
client_id = str(uuid.uuid4())


def queue_prompt(user_prompt: str):
    # 1. 定義工作流程 JSON 範本，把 user_prompt 塞進去
    workflow_graph = {
        "1": {
            "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"},
            "class_type": "CheckpointLoaderSimple"
        },
        # 這裡把使用者的 prompt 塞到第一個 CLIPTextEncode 節點
        "2": {
            "inputs": {"text": user_prompt, "clip": ["1", 1]},
            "class_type": "CLIPTextEncode"
        },
        # 範例保留第二組負面提示
        "3": {
            "inputs": {
                "text": "(low quality, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
                "clip": ["1", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "4": {
            "inputs": {
                "seed": 440871023236812,
                "steps": 20,
                "cfg": 8,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["15", 0]
            },
            "class_type": "KSampler"
        },
        "7": {
            "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
            "class_type": "SaveImage"
        },
        "8": {
            "inputs": {"samples": ["4", 0], "vae": ["9", 0]},
            "class_type": "VAEDecode"
        },
        "9": {
            "inputs": {"vae_name": "kl-f8-anime2.safetensors"},
            "class_type": "VAELoader"
        },
        "15": {
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
            "class_type": "EmptyLatentImage"
        }
    }

    # 2. 包裝成 ComfyUI /prompt API 要求的格式
    payload = {
        "prompt": workflow_graph,
        "client_id": client_id
    }

    # 3. 送到 ComfyUI
    try:
        req = urllib.request.Request(
            f"{COMFYUI_API_URL}/prompt",               # 正確端點
            # 包裹 workflow_graph 與 client_id
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        # 範例回傳：{"prompt_id":123,"number":1}
        return result
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        app.logger.error(f"ComfyUI 400 回應：{error_body}")
        return None


def wait_for_completion(prompt_id, client_id):
    """
    建立 WebSocket 連線等待指定 prompt_id 任務完成
    """
    ws_url = f"ws://127.0.0.1:8188/ws?clientId={client_id}"
    print("🕐 等待 ComfyUI 任務完成...")
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message.get("type") == "executing":
                    data = message.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")


def get_history(prompt_id):
    """
    透過 /history/<prompt_id> API 取得 ComfyUI 任務輸出紀錄
    """
    url = f"http://127.0.0.1:8188/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print(
            f"📜 history API 回應: {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}


def find_latest_png():
    """
    若 /history API 沒有提供檔名，則在 comfyui_output_dir 搜尋最新的 .png 檔案
    """
    png_files = [f for f in os.listdir(
        comfyui_output_dir) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(
        os.path.join(comfyui_output_dir, f)))
    print(f"🎞 找到最新的 .png 檔案: {latest_png}")
    return latest_png


def get_final_image_filename(prompt_id):
    """
    從 /history/<prompt_id> 中找出最終輸出的圖片檔名，
    如未找到則使用 find_latest_png()
    """
    history = get_history(prompt_id)
    if not history:
        print("⚠️ history API 回應為空，改用檔案搜尋。")
        return find_latest_png()

    outputs = history.get("outputs", {})
    image_node = outputs.get("7", {})
    if "images" in image_node:
        for info in image_node["images"]:
            filename = info.get("filename")
            if filename and filename.lower().endswith(".png"):
                print(f"🎞 從 API 取得圖片檔名: {filename}")
                return filename

    print("⚠️ history API 未提供圖片檔名，改用檔案搜尋。")
    return find_latest_png()


def move_output_files(prompt_id):
    """
    將 comfyui_output_dir 中的圖片檔搬移到 target_dir，
    並在檔名中加入時間戳作為唯一標識
    """
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 無法取得圖片檔案名稱！")
        return None

    name, ext = os.path.splitext(image_filename)
    unique_filename = f"{name}_{int(time.time())}{ext}"
    source_path = os.path.join(comfyui_output_dir, image_filename)
    target_path = os.path.join(target_dir, unique_filename)

    if not os.path.exists(source_path):
        print(f"⚠️ 找不到來源檔案: {source_path}")
        return None

    try:
        shutil.move(source_path, target_path)
        print(f"✅ 搬移成功: {source_path} → {target_path}")
        return unique_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None


# =============================
# Flask 路由
# =============================

@app.route("/generate_image", methods=["POST"])
def generate_image_endpoint():
    """
    接收前端描述與參數，轉發給內網生圖服務，
    等待任務完成後搬移檔案，並回傳 HTTPS 圖片連結
    """
    data = request.json
    description = data.get("text", "").strip()
    if not description:
        return jsonify({"error": "請提供有效的描述文字"}), 400

    # ——— 新增：Checkpoint 名稱映射 ———
    checkpoint_map = {
        "anythingelseV4_v45.safetensors":               "anythingelseV4_v45.safetensors",
        "flux1-dev.safetensors":                         "flux1-dev.safetensors",
        # max → mix
        "meanimax_v12Final.safetensors":                 "meinamix_v12Final.safetensors",
        "realisticVisionV51_v51VAE.safetensors":         "realisticVisionV51_v51VAE.safetensors",
        "sdxlUnstableDiffusers_nihilanth.safetensors":   "sdxlUnstableDiffusers_nihilmania.safetensors",  # anth → mania
        # v9 → v5, RunDiffusion → Rundiffusion
        "sdxlYamersRealistic5_v9RunDiffusion.safetensors": "sdxlYamersRealistic5_v5Rundiffusion.safetensors"
    }
    raw_ckpt = data.get("checkpoint", "meanimax_v12Final.safetensors")
    checkpoint_name = checkpoint_map.get(raw_ckpt, raw_ckpt)
    vae_name = data.get("vae", "kl-f8-anime2.safetensors")
    # ——————————————————————————————

    try:
        cfg_scale = int(data.get("cfg_scale", 7))
    except ValueError:
        cfg_scale = 7
    sampler_name = data.get("sampler", "euler")
    scheduler = data.get("scheduler", "normal")
    try:
        seed = int(data.get("seed", 103))
    except ValueError:
        seed = 103

    print("🔹 收到前端參數:", data)

    # ComfyUI 工作流程 JSON 範本
    prompt_text = """
{
  "1": {
    "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"},
    "class_type": "CheckpointLoaderSimple"
  },
  "2": {
    "inputs": {"text": "", "clip": ["1", 1]},
    "class_type": "CLIPTextEncode"
  },
  "3": {
    "inputs": {
      "text": "(low quality, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode"
  },
  "4": {
    "inputs": {
      "seed": 440871023236812,
      "steps": 20,
      "cfg": 8,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["3", 0],
      "latent_image": ["15", 0]
    },
    "class_type": "KSampler"
  },
  "7": {
    "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    "class_type": "SaveImage"
  },
  "8": {
    "inputs": {"samples": ["4", 0], "vae": ["9", 0]},
    "class_type": "VAEDecode"
  },
  "9": {
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"},
    "class_type": "VAELoader"
  },
  "15": {
    "inputs": {"width": 512, "height": 512, "batch_size": 1},
    "class_type": "EmptyLatentImage"
  }
}
"""
    try:
        prompt = json.loads(prompt_text)
    except json.JSONDecodeError as e:
        return jsonify({"error": "工作流程 JSON 格式錯誤", "details": str(e)}), 500

    # ——— 把映射後的 checkpoint 與 vae 寫入 workflow JSON ———
    prompt["1"]["inputs"]["ckpt_name"] = checkpoint_name
    prompt["9"]["inputs"]["vae_name"] = vae_name
    # ——————————————————————————————————————————————

    # 填入其它使用者參數
    prompt["2"]["inputs"]["text"] = description
    prompt["4"]["inputs"]["cfg"] = cfg_scale
    prompt["4"]["inputs"]["sampler_name"] = sampler_name
    prompt["4"]["inputs"]["scheduler"] = scheduler
    prompt["4"]["inputs"]["seed"] = seed

    print("🚀 發送工作流程到 ComfyUI...")


    # 原本是直接拿到 JSON dict
    # resp_data = queue_prompt(prompt)
    # 改成拿到 response 物件
    response = queue_prompt(prompt)

    # 1. 檢查 HTTP 狀態
    if response.status_code != 200:
    # 整包文字一起丟出來看錯誤
        raise RuntimeError(
            f"ComfyUI API 錯誤：{response.status_code} {response.text}")

    # 2. 解析 JSON
    resp_data = response.json()

    # 3. 印出來看看裡面到底長什麼樣
    print("🔍 ComfyUI 回傳原始資料：", resp_data)

    if not resp_data or "prompt_id" not in resp_data:
        return jsonify({"error": "ComfyUI API 回應錯誤"}), 500

    prompt_id = resp_data["prompt_id"]
    client_id = resp_data["client_id"]
    print(f"🔹 取得 prompt_id: {prompt_id}, client_id: {client_id}")

    wait_for_completion(prompt_id, client_id)
    time.sleep(5)

    print("✅ 任務完成，開始搬移圖片檔案...")
    unique_filename = move_output_files(prompt_id)
    if not unique_filename:
        return jsonify({"error": "搬移圖片失敗"}), 500

    # 回傳 HTTPS 圖片 URL
    image_url = f"{IMAGE_BASE_URL}/get_image/{unique_filename}?t={int(time.time())}"
    print("🔹 回傳圖片 URL:", image_url)
    return jsonify({"image_url": image_url})


@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    """
    提供搬移後的圖片檔案下載或顯示。如果檔案不存在，回傳 404
    """
    file_path = os.path.join(target_dir, filename)
    if not os.path.exists(file_path):
        print(f"⚠️ 找不到檔案: {file_path}")
        return jsonify({"error": "檔案不存在"}), 404
    return send_from_directory(target_dir, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
