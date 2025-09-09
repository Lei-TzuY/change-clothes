import json
import os
import shutil
import time
import uuid
import urllib.request
import websocket  # 請先安裝：pip install websocket-client
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from collections import OrderedDict
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# -------------------------------------------------------------------
# CORS 設定：開發階段允許所有網域；正式上線時請改為限制特定網域
# -------------------------------------------------------------------
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
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
BACKEND_SERVER   = "http://172.24.11.7:5011"

# -------------------------------------------------------------------
# Cloudflare Tunnel 對外提供的 HTTPS 網域（必須設定為 HTTPS）
# -------------------------------------------------------------------
IMAGE_BASE_URL = "https://api-lora.picturesmagician.com"

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

def queue_prompt(prompt):
    """
    發送工作流程 JSON 到 ComfyUI 的 /prompt API，並回傳 prompt_id 與 client_id
    """
    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    url = "http://127.0.0.1:8188/prompt"
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
        print(f"📜 history API 回應: {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def find_latest_png():
    """
    若 /history API 沒有提供檔名，則在 comfyui_output_dir 搜尋最新的 .png 檔案
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
    接收前端描述與參數，轉發給 ComfyUI，等待完成，搬移檔案並回傳 HTTPS 圖片連結
    """
    data = request.json
    description = data.get("text", "").strip()
    if not description:
        return jsonify({"error": "請提供有效的描述文字"}), 400

    # ——— 1. 解析基本參數 ———
    # Checkpoint 名稱映射
    checkpoint_map = {
        "anythingelseV4_v45.safetensors":               "anythingelseV4_v45.safetensors",
        "flux1-dev.safetensors":                        "flux1-dev.safetensors",
        "meanimax_v12Final.safetensors":                "meinamix_v12Final.safetensors",        
        "realisticVisionV51_v51VAE.safetensors":        "realisticVisionV51_v51VAE.safetensors",
        "sdxlUnstableDiffusers_nihilanth.safetensors":  "sdxlUnstableDiffusers_nihilmania.safetensors",
        "sdxlYamersRealistic5_v9RunDiffusion.safetensors":"sdxlYamersRealistic5_v5Rundiffusion.safetensors"
    }
    raw_ckpt       = data.get("checkpoint", "meanimax_v12Final.safetensors")
    checkpoint     = checkpoint_map.get(raw_ckpt, raw_ckpt)
    vae            = data.get("vae", "kl-f8-anime2.safetensors")
    try:
        cfg_scale      = int(data.get("cfg_scale", 7))
    except ValueError:
        cfg_scale      = 7
    sampler        = data.get("sampler", "euler")
    scheduler      = data.get("scheduler", "normal")
    try:
        seed           = int(data.get("seed", 103))
    except ValueError:
        seed           = 103

    # ——— 2. 解析 LoRA 參數 ———
    lora_name      = data.get("lora_name", "").strip()
    try:
        strength_model = float(data.get("strength_model", 0.0))
    except (TypeError, ValueError):
        strength_model = 0.0
    try:
        strength_clip  = float(data.get("strength_clip", 1.0))
    except (TypeError, ValueError):
        strength_clip  = 1.0

    # ——— 3. 列印所有參數，方便除錯 ———
    print("🔹 收到前端參數:", data)
    print(f"   -> checkpoint:      {checkpoint}")
    print(f"   -> vae:             {vae}")
    print(f"   -> cfg_scale:       {cfg_scale}")
    print(f"   -> sampler:         {sampler}")
    print(f"   -> scheduler:       {scheduler}")
    print(f"   -> seed:            {seed}")
    print(f"   -> lora_name:       {lora_name}")
    print(f"   -> strength_model:  {strength_model}")
    print(f"   -> strength_clip:   {strength_clip}")

    # ——— 4. 建立 ComfyUI workflow JSON ———
    prompt_text = """
{
  "1":  {"class_type":"CheckpointLoaderSimple", "inputs":{"ckpt_name":"meinamix_v12Final.safetensors"}},
  "2":  {"class_type":"CLIPTextEncode",      "inputs":{"text":"", "clip":["1",1]}},
  "3":  {"class_type":"CLIPTextEncode",      "inputs":{"text":"(low quality, worst quality...)", "clip":["1",1]}},
  "4":  {"class_type":"KSampler",            "inputs":{"seed":440871023236812,"steps":20,"cfg":8,"sampler_name":"euler","scheduler":"normal","denoise":1,"model":["1",0],"positive":["2",0],"negative":["3",0],"latent_image":["15",0]}},
  "7":  {"class_type":"SaveImage",           "inputs":{"filename_prefix":"ComfyUI","images":["8",0]}},
  "8":  {"class_type":"VAEDecode",           "inputs":{"samples":["4",0],"vae":["9",0]}},
  "9":  {"class_type":"VAELoader",           "inputs":{"vae_name":"kl-f8-anime2.safetensors"}},
  "15": {"class_type":"EmptyLatentImage",    "inputs":{"width":512,"height":512,"batch_size":1}}
}
"""
    try:
        prompt = json.loads(prompt_text)
    except json.JSONDecodeError as e:
        return jsonify({"error": "工作流程 JSON 格式錯誤", "details": str(e)}), 500

    # ——— 5. 填入使用者參數 ———
    prompt["1"]["inputs"]["ckpt_name"]      = checkpoint
    prompt["9"]["inputs"]["vae_name"]       = vae
    prompt["2"]["inputs"]["text"]           = description
    prompt["4"]["inputs"]["cfg"]            = cfg_scale
    prompt["4"]["inputs"]["sampler_name"]   = sampler
    prompt["4"]["inputs"]["scheduler"]      = scheduler
    prompt["4"]["inputs"]["seed"]           = seed

    # ——— 6. 插入 LoRA 節點（若有指定） ———
    if lora_name:
        prompt["10"] = {
            "class_type":"LoraLoader",
            "inputs":{
                "lora_name":      lora_name,
                "strength_model": strength_model,
                "strength_clip":  strength_clip,
                "model":          ["1",0],
                "clip":           ["1",1]
            }
        }
        # 把 KSampler 的 model 由 ["1",0] 改成 ["10",0]
        prompt["4"]["inputs"]["model"] = ["10",0]

    # ——— 7. 送到 ComfyUI 並等待完成 ———
    resp_data = queue_prompt(prompt)
    if not resp_data or "prompt_id" not in resp_data:
        return jsonify({"error": "ComfyUI API 回應錯誤"}), 500

    prompt_id = resp_data["prompt_id"]
    client_id = resp_data["client_id"]
    print(f"🔹 prompt_id={prompt_id}, client_id={client_id}")

    wait_for_completion(prompt_id, client_id)
    time.sleep(5)

    # ——— 8. 搬移輸出檔案 → HTTPS 連結回傳 ———
    unique_fn = move_output_files(prompt_id)
    if not unique_fn:
        return jsonify({"error": "搬移圖片失敗"}), 500

    image_url = f"{IMAGE_BASE_URL}/get_image/{unique_fn}?t={int(time.time())}"
    print(f"🔹 回傳圖片 URL: {image_url}")
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
    app.run(host="0.0.0.0", port=5011, debug=False)
