import json
import os
import shutil
import time
import uuid
import websocket  # pip install websocket-client
import urllib.request
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ================================
# ComfyUI 及資料夾設定
# ================================
SERVER_ADDR       = "127.0.0.1:8188"
COMFYUI_OUT_DIR   = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
TARGET_DIR        = r"D:\大模型圖生圖"
TEMP_INPUT_DIR    = r"D:\大模型圖生圖\temp_input"
EXTERNAL_BASE_URL = "https://image.picturesmagician.com"

os.makedirs(TARGET_DIR, exist_ok=True)
os.makedirs(TEMP_INPUT_DIR, exist_ok=True)

# ================================
# 與 ComfyUI 互動：queue prompt
# ================================
def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": prompt, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    url       = f"http://{SERVER_ADDR}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

# ================================
# 等待 ComfyUI 完成：處理非 UTF-8 frame
# ================================
def wait_for_completion(prompt_id, client_id):
    ws_url = f"ws://{SERVER_ADDR}/ws?clientId={client_id}"
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            raw = ws.recv()
            # 若為 bytes，嘗試 UTF-8 解碼，失敗則跳過
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
        # 只印出非解碼問題的錯誤
        print(f"❌ WebSocket 監聽錯誤: {e}")

# ================================
# Helpers: history & file moves
# ================================
def get_history(prompt_id):
    try:
        url = f"http://{SERVER_ADDR}/history/{prompt_id}"
        with urllib.request.urlopen(url) as resp:
            hist = json.loads(resp.read())
        return hist.get(prompt_id, {})
    except:
        return {}

def find_latest_png():
    pngs = [f for f in os.listdir(COMFYUI_OUT_DIR) if f.lower().endswith(".png")]
    return max(pngs, key=lambda f: os.path.getctime(os.path.join(COMFYUI_OUT_DIR, f))) if pngs else None

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
    src = os.path.join(COMFYUI_OUT_DIR, fn)
    dst = os.path.join(TARGET_DIR, fn)
    if os.path.exists(src):
        shutil.move(src, dst)
        return fn
    return None

# ================================
# 主路由：接受 form-data 圖片上傳 + 參數
# ================================
@app.route("/image_to_image", methods=["POST"])
def image_to_image():
    # 1) 圖片檢查與儲存
    img = request.files.get("image")
    if not img or img.filename == "":
        return jsonify({"error": "未上傳圖片"}), 400
    filename = secure_filename(img.filename)
    input_path = os.path.join(TEMP_INPUT_DIR, filename)
    img.save(input_path)
    print(f"✅ 圖片已保存: {input_path}")

    # 2) 讀取表單參數
    cfg_scale        = int(request.form.get("cfgScale", 7))
    sampler_name     = request.form.get("samplerName", "euler")
    scheduler        = request.form.get("scheduler", "normal")
    denoise_strength = float(request.form.get("denoiseStrength", 0.7))
    vae_name         = request.form.get("vaeName", "kl-f8-anime2.safetensors")
    ckpt_name        = request.form.get("checkpointName", "meinamix_v12Final.safetensors")
    seed_str         = request.form.get("seed", "")
    prompt_text      = request.form.get("prompt", "").strip()
    lora_name        = request.form.get("loraName", "").strip()
    strength_model   = float(request.form.get("loraStrengthModel", 0.0))
    strength_clip    = float(request.form.get("loraStrengthClip", 1.0))

    try:
        seed = int(seed_str) if seed_str else int(uuid.uuid4().int % 1000000)
    except:
        seed = int(uuid.uuid4().int % 1000000)

    # 3) 參數換行列印
    print("🔹 收到前端參數：")
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

    # 4) ComfyUI Workflow 範本（含 LoRA 節點）&#8203;:contentReference[oaicite:0]{index=0}&#8203;:contentReference[oaicite:1]{index=1}
    workflow_template = r"""
{
  "1":  {"inputs":{"ckpt_name":"meinamix_v12Final.safetensors"},"class_type":"CheckpointLoaderSimple"},
  "2":  {"inputs":{"text":"","clip":["15",1]},"class_type":"CLIPTextEncode"},
  "3":  {"inputs":{"text":"","clip":["15",1]},"class_type":"CLIPTextEncode"},
  "4":  {"inputs":{"seed":0,"steps":20,"cfg":7,"sampler_name":"euler","scheduler":"normal","denoise":0.7,"model":["15",0],"positive":["2",0],"negative":["3",0],"latent_image":["14",0]},"class_type":"KSampler"},
  "7":  {"inputs":{"filename_prefix":"ComfyUI","images":["8",0]},"class_type":"SaveImage"},
  "8":  {"inputs":{"samples":["4",0],"vae":["9",0]},"class_type":"VAEDecode"},
  "9":  {"inputs":{"vae_name":"kl-f8-anime2.safetensors"},"class_type":"VAELoader"},
  "13": {"inputs":{"pixels":["16",0],"vae":["9",0]},"class_type":"VAEEncode"},
  "14": {"inputs":{"upscale_method":"nearest-exact","width":512,"height":512,"crop":"disabled","samples":["13",0]},"class_type":"LatentUpscale"},
  "15": {"inputs":{"lora_name":"super-vanilla-newlora-ver1-p.safetensors","strength_model":0,"strength_clip":1,"model":["1",0],"clip":["1",1]},"class_type":"LoraLoader"},
  "16": {"inputs":{"image_path":""},"class_type":"ZwngLoadImagePathOrURL"}
}
""".strip()

    prompt = json.loads(workflow_template)
    # 5) 動態填入使用者設定
    prompt["1"]["inputs"]["ckpt_name"]      = ckpt_name
    prompt["9"]["inputs"]["vae_name"]       = vae_name
    prompt["2"]["inputs"]["text"]           = prompt_text
    prompt["4"]["inputs"]["seed"]           = seed
    prompt["4"]["inputs"]["cfg"]            = cfg_scale
    prompt["4"]["inputs"]["sampler_name"]   = sampler_name
    prompt["4"]["inputs"]["scheduler"]      = scheduler
    prompt["4"]["inputs"]["denoise"]        = denoise_strength
    prompt["16"]["inputs"]["image_path"]    = input_path.replace("\\", "/")
    prompt["15"]["inputs"]["lora_name"]     = lora_name
    prompt["15"]["inputs"]["strength_model"]= strength_model
    prompt["15"]["inputs"]["strength_clip"] = strength_clip

    # 6) 發送至 ComfyUI，等待完成，搬檔並回傳
    resp = queue_prompt(prompt)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 回應錯誤"}), 500

    pid, cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid, cid)
    time.sleep(3)

    fn = move_output_files(pid)
    if not fn:
        return jsonify({"error": "圖片搬移失敗"}), 500

    image_url = f"{EXTERNAL_BASE_URL}/get_image/{fn}?t={int(time.time())}"
    return jsonify({"image_url": image_url})

# ================================
# 靜態提供已搬移的圖片
# ================================
@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    return send_from_directory(TARGET_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
