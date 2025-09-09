import json
import os
import shutil
import time
import uuid
import websocket  # 請確保已安裝 websocket-client
import urllib.request
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器位址（假設在本機）
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir = r"D:\大模型文生圖"
os.makedirs(target_dir, exist_ok=True)  # 確保目標資料夾存在

# =============================
# 函式定義
# =============================

def queue_prompt(prompt):
    """
    發送工作流程 (Workflow) JSON 到 ComfyUI 的 /prompt API，
    並回傳包含 prompt_id 與該任務專用 client_id 的結果。
    """
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": prompt,
        "client_id": client_id
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    """
    建立新的 WebSocket 連線監聽指定 prompt_id 的執行狀態。
    當收到 'executing' 訊息，且其中的 node 為 None（且 prompt_id 相符）時，
    認為該流程已完成。
    """
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
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
    透過 /history/<prompt_id> API 取得該任務的輸出紀錄，並回傳對應的 JSON。
    """
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print(f"📜 Debug: history API 回應 = {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def find_latest_png():
    """
    若 /history API 未提供有效檔名，則於 ComfyUI 輸出資料夾中搜尋最新的 .png 檔。
    """
    png_files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎞 找到最新的 .png 檔案: {latest_png}")
    return latest_png

def get_final_image_filename(prompt_id):
    """
    從 /history/<prompt_id> 中找出最終輸出的圖片檔名，
    如果無法從 API 找到，則改用檔案搜尋。
    """
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_png()
    outputs = history.get("outputs", {})
    image_node = outputs.get("7", {})
    if "images" in image_node:
        for info in image_node["images"]:
            filename = info.get("filename")
            if filename and filename.lower().endswith(".png"):
                print(f"🎞 從 API 取得圖片檔名: {filename}")
                return filename
    print("⚠️ /history API 未提供圖片檔名，改用檔案搜尋。")
    return find_latest_png()

def move_output_files(prompt_id):
    """
    將 get_final_image_filename() 找到的 .png 檔搬移到指定的目標資料夾，
    並回傳搬移後的檔案名稱（同時為檔案名稱增加唯一標識）。
    """
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 無法取得圖片檔案名稱！")
        return None

    # 產生唯一檔名：在原本檔名中加入時間戳
    name, ext = os.path.splitext(image_filename)
    unique_filename = f"{name}_{int(time.time())}{ext}"

    source_path = os.path.join(comfyui_output_dir, image_filename)
    target_path = os.path.join(target_dir, unique_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return None
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
        return unique_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None

# =============================
# Flask API Endpoint
# =============================

@app.route("/generate_image", methods=["POST"])
def generate_image_endpoint():
    """
    接收前端的描述文字，發送工作流程給 ComfyUI，
    等待任務完成後搬移輸出圖片，並回傳圖片 URL。
    """
    data = request.json
    description = data.get("text", "").strip()
    if not description:
        return jsonify({"error": "請提供有效的描述文字"}), 400

    # 使用預設工作流程 JSON 模板
    prompt_text = """
{
  "1": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Checkpoint加载器（简易）"
    }
  },
  "2": {
    "inputs": {
      "text": "",
      "clip": [
        "1",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "正向提示詞"
    }
  },
  "3": {
    "inputs": {
      "text": "(low quality, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
      "clip": [
        "1",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "反向提示詞"
    }
  },
  "4": {
    "inputs": {
      "seed": 440871023236812,
      "steps": 20,
      "cfg": 8,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": [
        "1",
        0
      ],
      "positive": [
        "2",
        0
      ],
      "negative": [
        "3",
        0
      ],
      "latent_image": [
        "15",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "K采样器"
    }
  },
  "7": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": [
        "8",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "保存图像"
    }
  },
  "8": {
    "inputs": {
      "samples": [
        "4",
        0
      ],
      "vae": [
        "9",
        0
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE解码"
    }
  },
  "9": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "加载VAE"
    }
  },
  "15": {
    "inputs": {
      "width": 512,
      "height": 512,
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage",
    "_meta": {
      "title": "空Latent图像"
    }
  }
}
"""
    try:
        prompt = json.loads(prompt_text)
    except json.JSONDecodeError as e:
        return jsonify({"error": "工作流程 JSON 格式錯誤", "details": str(e)}), 500

    # 將前端傳入的描述文字設定至正向提示詞
    prompt["2"]["inputs"]["text"] = description
    print("用戶提示詞:",prompt["2"]["inputs"]["text"])
    # 如有需要，可在此調整其他參數
    prompt["4"]["inputs"]["cfg"] = 7
    prompt["4"]["inputs"]["sampler_name"] = "dpmpp_2m_sde"
    prompt["4"]["inputs"]["scheduler"] = "karras"
    prompt["4"]["inputs"]["seed"] = 103

    print("🚀 發送工作流程到 ComfyUI...")
    response_data = queue_prompt(prompt)
    if not response_data or "prompt_id" not in response_data:
        return jsonify({"error": "API 回應錯誤，請檢查 ComfyUI 是否在運行"}), 500

    prompt_id = response_data["prompt_id"]
    client_id = response_data["client_id"]
    print(f"🆔 取得 prompt_id: {prompt_id}")

    # 等待任務完成
    wait_for_completion(prompt_id, client_id)

    # 延遲等待 ComfyUI 的輸出更新（根據需求調整延遲時間）
    time.sleep(5)

    print("✅ 任務正常完成，開始搬移輸出圖片。")
    image_filename = move_output_files(prompt_id)
    if not image_filename:
        return jsonify({"error": "搬移圖片失敗"}), 500

    # 組合圖片 URL，並加入查詢參數防止瀏覽器快取
    image_url = request.host_url.rstrip("/") + "/get_image/" + image_filename + f"?t={int(time.time())}"
    return jsonify({"image_url": image_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    """
    提供生成的圖片檔案下載或顯示
    """
    return send_from_directory(target_dir, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
