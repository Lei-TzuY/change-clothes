import json
import os
import shutil
import time
import uuid
import websocket  # pip install websocket-client
import urllib.request
import urllib.error
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器位址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir = r"D:\大模型圖生圖"
temp_input_dir = r"D:\大模型圖生圖\temp_input"  # 用於暫存上傳圖片
os.makedirs(target_dir, exist_ok=True)
os.makedirs(temp_input_dir, exist_ok=True)

# 外網對外提供的域名（Cloudflare Tunnel 提供的 HTTPS 網域）
EXTERNAL_URL = "https://image.picturesmagician.com"

# =============================
# 函式定義
# =============================
def queue_prompt(prompt):
    """
    發送工作流程 JSON 至 ComfyUI /prompt API，
    並回傳包含 prompt_id 與 client_id 的結果。
    """
    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"❌ HTTPError: {e.code} {error_body}")
        return None
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    """
    透過 WebSocket 監聽指定 prompt_id 的任務狀態，
    當收到執行完成訊息時停止等待。
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
    呼叫 /history API 取得任務輸出紀錄。
    """
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print(f"📜 history API 回應:\n{json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def find_latest_png():
    """
    若 history API 無法取得圖片檔名，則於 ComfyUI 輸出資料夾中搜尋最新 .png 檔案。
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
    從 history API 或檔案搜尋取得最終輸出圖片檔名。
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
    print("⚠️ API 未提供圖片檔名，改用檔案搜尋。")
    return find_latest_png()

def move_output_files(prompt_id):
    """
    將輸出圖片從 ComfyUI 輸出資料夾搬移到目標資料夾，
    並回傳檔名。
    """
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 無法取得圖片檔案名稱！")
        return None
    source_path = os.path.join(comfyui_output_dir, image_filename)
    target_path = os.path.join(target_dir, image_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return None
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
        return image_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None

# =============================
# 圖生圖 API Endpoint
# =============================
@app.route("/image_to_image", methods=["POST"])
def image_to_image():
    # 檢查是否有上傳圖片
    if "image" not in request.files:
        return jsonify({"error": "未上傳圖片"}), 400
    uploaded_file = request.files["image"]
    if uploaded_file.filename == "":
        return jsonify({"error": "未選擇圖片檔案"}), 400
    filename = secure_filename(uploaded_file.filename)
    input_image_path = os.path.join(temp_input_dir, filename)
    uploaded_file.save(input_image_path)
    print(f"✅ 已儲存上傳圖片：{input_image_path}")

    # 取得其他表單參數
    cfg_scale = request.form.get("cfgScale", "7")
    sampler_name = request.form.get("samplerName", "euler")
    scheduler = request.form.get("scheduler", "karras")
    seed = request.form.get("seed", "")
    # 讀取提示詞參數（可能是經翻譯後的文字）
    prompt_text = request.form.get("prompt", "").strip()
    
    try:
        cfg_scale = int(cfg_scale)
    except:
        cfg_scale = 7
    try:
        seed = int(seed) if seed != "" else int(uuid.uuid4().int % 1000000)
    except:
        seed = int(uuid.uuid4().int % 1000000)
    
    print("收到參數設定：")
    print(f"CFG 強度: {cfg_scale}")
    print(f"採樣器: {sampler_name}")
    print(f"調度器: {scheduler}")
    print(f"種子: {seed}")
    print(f"提示詞: {prompt_text}")

    # 工作流程 JSON 模板
    workflow_template = r"""
{
  "1": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {"title": "Checkpoint加载器（简易）"}
  },
  "2": {
    "inputs": {
      "text": "a girl",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "正向提示詞"}
  },
  "3": {
    "inputs": {
      "text": "(low quality, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "反向提示詞"}
  },
  "4": {
    "inputs": {
      "seed": 0,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "dpmpp_2m_sde",
      "scheduler": "karras",
      "denoise": 0.7,
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["3", 0],
      "latent_image": ["14", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "K采样器"}
  },
  "7": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": ["8", 0]
    },
    "class_type": "SaveImage",
    "_meta": {"title": "保存图像"}
  },
  "8": {
    "inputs": {
      "samples": ["4", 0],
      "vae": ["9", 0]
    },
    "class_type": "VAEDecode",
    "_meta": {"title": "VAE解码"}
  },
  "9": {
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"},
    "class_type": "VAELoader",
    "_meta": {"title": "加载VAE"}
  },
  "14": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 512,
      "height": 512,
      "crop": "disabled",
      "samples": ["13", 0]
    },
    "class_type": "LatentUpscale",
    "_meta": {"title": "缩放Latent"}
  },
  "13": {
    "inputs": {
      "pixels": ["17", 0],
      "vae": ["9", 0]
    },
    "class_type": "VAEEncode",
    "_meta": {"title": "VAE编码"}
  },
  "17": {
    "inputs": {
      "image": "",
      "force_size": "Disabled",
      "custom_width": 512,
      "custom_height": 512
    },
    "class_type": "VHS_LoadImagePath",
    "_meta": {"title": "Load Image (Path)"}
  }
}
""".strip()
    
    try:
        workflow = json.loads(workflow_template)
    except Exception as e:
        return jsonify({"error": "工作流程 JSON 格式錯誤", "details": str(e)}), 500

    # 套用使用者參數至工作流程
    workflow["4"]["inputs"]["cfg"] = cfg_scale
    workflow["4"]["inputs"]["sampler_name"] = sampler_name
    workflow["4"]["inputs"]["scheduler"] = scheduler
    workflow["4"]["inputs"]["seed"] = seed
    workflow["17"]["inputs"]["image"] = input_image_path.replace("\\", "/")
    if prompt_text:
        workflow["2"]["inputs"]["text"] = prompt_text

    print("🚀 發送工作流程至 ComfyUI：")
    print(json.dumps(workflow, indent=4, ensure_ascii=False))

    response = queue_prompt(workflow)
    if not response or "prompt_id" not in response:
        return jsonify({"error": "API 回應錯誤，請檢查 ComfyUI 是否在運行"}), 500

    prompt_id = response["prompt_id"]
    client_id = response["client_id"]
    print(f"🆔 取得 prompt_id: {prompt_id}")

    wait_for_completion(prompt_id, client_id)

    print("✅ 任務完成，開始搬移輸出圖片。")
    output_filename = move_output_files(prompt_id)
    if not output_filename:
        return jsonify({"error": "搬移圖片失敗"}), 500

    # 使用外網域名建立圖片 URL
    image_url = EXTERNAL_URL + "/get_image/" + output_filename + f"?t={int(time.time())}"
    return jsonify({"image_url": image_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    return send_from_directory(target_dir, filename)

# =============================
# 啟動 Flask 伺服器
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
