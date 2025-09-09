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
import base64

app = Flask(__name__)
CORS(app)

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address   = "127.0.0.1:8188"  # ComfyUI 伺服器位址（假設在本機）
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir       = r"D:\大模型圖生圖"
temp_input_dir   = r"D:\大模型圖生圖\temp_input"  # 用於暫存前端繪製圖像
os.makedirs(target_dir, exist_ok=True)
os.makedirs(temp_input_dir, exist_ok=True)

# 外網對外提供的域名（例如 Cloudflare Tunnel 提供的 HTTPS 網域）
EXTERNAL_URL     = "https://draw.picturesmagician.com"

# =============================
# 工具函數：Queue、等待、歷史紀錄、文件搬移等
# =============================
def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": prompt, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    url       = f"http://{server_address}/prompt"
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
    png_files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎞 找到最新的 .png 檔案: {latest_png}")
    return latest_png

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    if not history:
        print("⚠️ history API 回應为空，改用檔案搜尋。")
        return find_latest_png()
    outputs    = history.get("outputs", {})
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
# 創意繪畫 API Endpoint
# =============================
@app.route("/convert-image", methods=["POST"])
def convert_image_endpoint():
    # force=True 確保解析 JSON
    data = request.get_json(force=True)

    # —— 修改處：列印完整 payload ——  
    print("▶ Received payload:", json.dumps(data, ensure_ascii=False))

    if not data or "image" not in data:
        return jsonify({"error": "未提供圖像資料"}), 400

    image_base64 = data["image"]
    try:
        header, encoded = image_base64.split(",", 1)
    except Exception as e:
        return jsonify({"error": "圖像資料格式錯誤", "details": str(e)}), 400

    file_ext = "png"
    if "jpeg" in header or "jpg" in header:
        file_ext = "jpg"
    try:
        file_bytes = base64.b64decode(encoded)
    except Exception as e:
        return jsonify({"error": "Base64 解碼錯誤", "details": str(e)}), 400

    filename = f"upload_{uuid.uuid4().hex}.{file_ext}"
    input_image_path = os.path.join(temp_input_dir, filename)
    with open(input_image_path, "wb") as f:
        f.write(file_bytes)
    print(f"✅ 已儲存繪製圖像：{input_image_path}")

    # —— 修改處：完整讀取前端所有參數 ——  
    cfg_scale        = data.get("cfgScale", "7")
    sampler_name     = data.get("samplerName", "euler")
    scheduler        = data.get("scheduler", "karras")
    denoise_strength = data.get("denoiseStrength", "0.7")
    vae_name         = data.get("vaeName", "kl-f8-anime2.safetensors")
    ckpt_name        = data.get("checkpointName", "meinamix_v12Final.safetensors")
    seed             = data.get("seed", "")
    prompt_text      = data.get("prompt", "").strip()

    # 型別轉換
    try:
        cfg_scale = int(cfg_scale)
    except:
        cfg_scale = 7
    try:
        denoise_strength = float(denoise_strength)
    except:
        denoise_strength = 0.7
    try:
        seed = int(seed) if seed != "" else int(uuid.uuid4().int % 1000000)
    except:
        seed = int(uuid.uuid4().int % 1000000)

    # —— 修改處：列印所有參數 ——  
    print("✅ 收到參數設定：")
    print(f"  • VAE 名稱         : {vae_name}")
    print(f"  • Checkpoint 名稱 : {ckpt_name}")
    print(f"  • CFG 強度        : {cfg_scale}")
    print(f"  • 採樣器           : {sampler_name}")
    print(f"  • 調度器           : {scheduler}")
    print(f"  • 去躁幅度         : {denoise_strength}")
    print(f"  • 隨機種子         : {seed}")
    print(f"  • 提示詞           : {prompt_text}")
    # — 修改處結束 —

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
    "class_type": "LoadImage",
    "_meta": {"title": "Load Image (Path)"}
  }
}
""".strip()
    try:
        workflow = json.loads(workflow_template)
    except Exception as e:
        return jsonify({"error": "工作流程 JSON 格式錯誤", "details": str(e)}), 500

    # —— 修改處：套用所有參數到工作流程 ——  
    workflow["1"]["inputs"]["ckpt_name"]     = ckpt_name
    workflow["9"]["inputs"]["vae_name"]      = vae_name
    workflow["4"]["inputs"]["cfg"]           = cfg_scale
    workflow["4"]["inputs"]["sampler_name"]  = sampler_name
    workflow["4"]["inputs"]["scheduler"]     = scheduler
    workflow["4"]["inputs"]["denoise"]       = denoise_strength
    workflow["4"]["inputs"]["seed"]          = seed
    workflow["17"]["inputs"]["image"]        = input_image_path
    if prompt_text:
        workflow["2"]["inputs"]["text"]      = prompt_text
    # — 修改處結束 —

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

    # 使用外網域名組成圖片 URL
    image_url = EXTERNAL_URL + "/get_image/" + output_filename + f"?t={int(time.time())}"
    return jsonify({"image_url": image_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    return send_from_directory(target_dir, filename)

# 新增 /image_to_image 路由，供 ComfyUI 讀取圖片檔案（若工作流程中 LoadImage 觸發）
@app.route("/image_to_image", methods=["POST"])
def load_image():
    data = request.get_json(force=True)
    image_path = data.get("image")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "圖像路徑不存在"}), 404
    ext = os.path.splitext(image_path)[1].lower()
    mimetype = "image/png" if ext == ".png" else "image/jpeg"
    with open(image_path, "rb") as f:
        content = f.read()
    return content, 200, {"Content-Type": mimetype}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
