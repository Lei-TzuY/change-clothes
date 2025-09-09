import json
import os
import shutil
import time
import uuid
import websocket  # pip install websocket-client
import urllib.request
import urllib.error
import base64
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ================================
# ComfyUI & 檔案資料夾設定
# ================================
server_address     = "127.0.0.1:8188"  # ComfyUI 伺服器位址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir         = r"D:\大模型創意繪畫\output"
temp_input_dir     = r"D:\大模型創意繪畫\temp_input"

# 確保資料夾存在
os.makedirs(target_dir, exist_ok=True)
os.makedirs(temp_input_dir, exist_ok=True)

# 外網域名，用於回傳最終圖片連結
EXTERNAL_URL = "https://draw-lora.picturesmagician.com"

# ================================
# 與 ComfyUI 溝通的輔助函式
# ================================
def queue_prompt(workflow):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": workflow, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    url       = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"❌ HTTPError {e.code}: {body}")
        return None
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            raw = ws.recv()
            if isinstance(raw, bytes):
                try:
                    raw = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
            if not isinstance(raw, str):
                continue
            msg = json.loads(raw)
            if msg.get("type") == "executing":
                data = msg.get("data", {})
                if data.get("node") is None and data.get("prompt_id") == prompt_id:
                    break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 監聽錯誤: {e}")

def get_history(prompt_id):
    try:
        url = f"http://{server_address}/history/{prompt_id}"
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read()).get(prompt_id, {})
    except Exception:
        return {}

def find_latest_png():
    pngs = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    return max(pngs, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f))) if pngs else None

def get_final_image_filename(prompt_id):
    hist = get_history(prompt_id)
    for info in hist.get("outputs", {}).get("7", {}).get("images", []):
        fn = info.get("filename")
        if fn and fn.lower().endswith(".png"):
            return fn
    return find_latest_png()

def move_output_files(prompt_id):
    fn = get_final_image_filename(prompt_id)
    if not fn:
        return None
    src = os.path.join(comfyui_output_dir, fn)
    dst = os.path.join(target_dir, fn)
    if os.path.exists(src):
        shutil.move(src, dst)
        return fn
    return None

# ================================
# 創意繪畫 API Endpoint
# ================================
@app.route("/convert-image", methods=["POST"])
def convert_image_endpoint():
    data = request.get_json(force=True)
    print("▶ Received payload:", json.dumps(data, ensure_ascii=False))

    # 驗證必填
    if not data or "image" not in data:
        return jsonify({"error": "未提供圖像資料"}), 400

    # 解析 Base64 圖像並儲存
    try:
        header, encoded = data["image"].split(",", 1)
        file_ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
        file_bytes = base64.b64decode(encoded)
    except Exception as e:
        return jsonify({"error": "圖像解析失敗", "details": str(e)}), 400

    fname            = f"upload_{uuid.uuid4().hex}.{file_ext}"
    input_path       = os.path.join(temp_input_dir, secure_filename(fname))
    with open(input_path, "wb") as f:
        f.write(file_bytes)
    print(f"✅ 已儲存繪製圖像：{input_path}")

    # 讀取並轉型參數
    cfg_scale        = int(data.get("cfgScale", 7))
    sampler_name     = data.get("samplerName", "euler")
    scheduler        = data.get("scheduler", "normal")
    denoise_strength = float(data.get("denoiseStrength", 0.7))
    vae_name         = data.get("vaeName", "kl-f8-anime2.safetensors")
    ckpt_name        = data.get("checkpointName", "meinamix_v12Final.safetensors")
    seed_val         = data.get("seed", "")
    prompt_text      = data.get("prompt", "").strip()
    lora_name        = data.get("loraName", "").strip()
    strength_model   = float(data.get("loraStrengthModel", 0.0))
    strength_clip    = float(data.get("loraStrengthClip", 1.0))

    try:
        seed = int(seed_val) if seed_val else int(uuid.uuid4().int % 1000000)
    except:
        seed = int(uuid.uuid4().int % 1000000)

    # 美化列印
    print("🔹 前端參數：")
    print(f"  • Checkpoint 名稱    : {ckpt_name}")
    print(f"  • VAE 名稱           : {vae_name}")
    print(f"  • CFG 強度           : {cfg_scale}")
    print(f"  • 採樣器             : {sampler_name}")
    print(f"  • 調度器             : {scheduler}")
    print(f"  • 去躁幅度           : {denoise_strength}")
    print(f"  • 隨機種子           : {seed}")
    print(f"  • 提示詞             : {prompt_text}")
    print(f"  • LoRA 名稱          : {lora_name}")
    print(f"  • LoRA 強度 (Model)  : {strength_model}")
    print(f"  • LoRA 強度 (CLIP)   : {strength_clip}")

    # ================================
    # ComfyUI Workflow JSON (含 LoRA 節點) :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}
    # ================================
    workflow_template = r"""
{
  "1":  {"inputs":{"ckpt_name":"meinamix_v12Final.safetensors"},"class_type":"CheckpointLoaderSimple"},
  "2":  {"inputs":{"text":"","clip":["15",1]},"class_type":"CLIPTextEncode"},
  "3":  {"inputs":{"text":"","clip":["15",1]},"class_type":"CLIPTextEncode"},
  "4":  {"inputs":{
           "seed":0,"steps":20,"cfg":7,
           "sampler_name":"euler","scheduler":"normal",
           "denoise":0.7,
           "model":["15",0],
           "positive":["2",0],"negative":["3",0],
           "latent_image":["14",0]
         },"class_type":"KSampler"},
  "7":  {"inputs":{"filename_prefix":"ComfyUI","images":["8",0]},"class_type":"SaveImage"},
  "8":  {"inputs":{"samples":["4",0],"vae":["9",0]},"class_type":"VAEDecode"},
  "9":  {"inputs":{"vae_name":"kl-f8-anime2.safetensors"},"class_type":"VAELoader"},
  "13": {"inputs":{"pixels":["16",0],"vae":["9",0]},"class_type":"VAEEncode"},
  "14": {"inputs":{
           "upscale_method":"nearest-exact",
           "width":512,"height":512,"crop":"disabled",
           "samples":["13",0]
         },"class_type":"LatentUpscale"},
  "15": {"inputs":{
           "lora_name":"super-vanilla-newlora-ver1-p.safetensors",
           "strength_model":0,"strength_clip":1,
           "model":["1",0],"clip":["1",1]
         },"class_type":"LoraLoader"},
  "16": {"inputs":{"image_path":""},"class_type":"ZwngLoadImagePathOrURL"}
}
""".strip()

    workflow = json.loads(workflow_template)
    # 動態填值
    workflow["1"]["inputs"]["ckpt_name"]       = ckpt_name
    workflow["9"]["inputs"]["vae_name"]        = vae_name
    workflow["2"]["inputs"]["text"]            = prompt_text
    workflow["3"]["inputs"]["text"]            = ""  # 可修改為負向提示
    workflow["4"]["inputs"]["seed"]            = seed
    workflow["4"]["inputs"]["cfg"]             = cfg_scale
    workflow["4"]["inputs"]["sampler_name"]    = sampler_name
    workflow["4"]["inputs"]["scheduler"]       = scheduler
    workflow["4"]["inputs"]["denoise"]         = denoise_strength
    workflow["16"]["inputs"]["image_path"]     = input_path.replace("\\", "/")
    workflow["15"]["inputs"]["lora_name"]      = lora_name
    workflow["15"]["inputs"]["strength_model"] = strength_model
    workflow["15"]["inputs"]["strength_clip"]  = strength_clip

    # 發送、等待、搬檔、回傳
    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 回應錯誤"}), 500

    prompt_id = resp["prompt_id"]
    client_id = resp["client_id"]
    wait_for_completion(prompt_id, client_id)
    time.sleep(2)

    fn = move_output_files(prompt_id)
    if not fn:
        return jsonify({"error": "圖片搬移失敗"}), 500

    url = f"{EXTERNAL_URL}/get_image/{fn}?t={int(time.time())}"
    return jsonify({"image_url": url})

# ================================
# 靜態路由：對外提供已搬移圖片
# ================================
@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    return send_from_directory(target_dir, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5014, debug=False)
