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

# ================================
# 參數列表與說明
# ================================
# image           : 上傳的原始圖片（文件流）
# cfgScale        : CFG 強度（提示詞嚴格度，通常 7～10）
# samplerName     : 採樣器（如 euler, dpmpp_2m_sde…）
# scheduler       : 調度器（如 karras, linear_quadratic…）
# denoiseStrength : 去躁幅度（0.0～1.0）
# vaeName         : VAE 名稱（如 kl-f8-anime2.safetensors）
# checkpointName  : Checkpoint 名稱（如 meinamix_v12Final.safetensors）
# seed            : 隨機種子（整數，可留空自動隨機）
# prompt          : 正向提示詞（翻譯後文字）

# ================================
# ComfyUI 伺服器與資料夾設定
# ================================
server_address    = "127.0.0.1:8188"  
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir         = r"D:\大模型圖生圖"
temp_input_dir     = r"D:\大模型圖生圖\temp_input"

os.makedirs(target_dir, exist_ok=True)
os.makedirs(temp_input_dir, exist_ok=True)

EXTERNAL_URL = "https://image.picturesmagician.com"

def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
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
                msg = json.loads(out)
                if msg.get("type") == "executing":
                    data = msg.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 錯誤: {e}")

def get_history(prompt_id):
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 取得 history 錯誤: {e}")
        return {}

def find_latest_png():
    pngs = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    if not pngs:
        print("🚫 沒有找到 PNG 檔")
        return None
    latest = max(pngs, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    return latest

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    outputs = history.get("outputs", {})
    node7 = outputs.get("7", {})
    if "images" in node7:
        for info in node7["images"]:
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

@app.route("/image_to_image", methods=["POST"])
def image_to_image():
    # 圖片檢查與儲存
    if "image" not in request.files:
        return jsonify({"error": "未上傳圖片"}), 400
    f = request.files["image"]
    if f.filename == "":
        return jsonify({"error": "無檔名"}), 400
    filename = secure_filename(f.filename)
    input_path = os.path.join(temp_input_dir, filename)
    f.save(input_path)
    print(f"✅ 已保存上傳: {input_path}")

    # 讀取所有參數
    cfg_scale        = request.form.get("cfgScale", "7")
    sampler_name     = request.form.get("samplerName", "euler")
    scheduler        = request.form.get("scheduler", "karras")
    denoise_strength = request.form.get("denoiseStrength", "0.7")
    vae_name         = request.form.get("vaeName", "kl-f8-anime2.safetensors")
    ckpt_name        = request.form.get("checkpointName", "meinamix_v12Final.safetensors")
    seed_str         = request.form.get("seed", "")
    prompt_text      = request.form.get("prompt", "").strip()

    # 參數型別轉換
    try:
        cfg_scale = int(cfg_scale)
    except:
        cfg_scale = 7
    try:
        denoise_strength = float(denoise_strength)
    except:
        denoise_strength = 0.7
    try:
        seed = int(seed_str) if seed_str else int(uuid.uuid4().int % 1000000)
    except:
        seed = int(uuid.uuid4().int % 1000000)

    # 日誌列印
    print("收到參數：")
    print(f"  CFG 強度       : {cfg_scale}")
    print(f"  採樣器         : {sampler_name}")
    print(f"  調度器         : {scheduler}")
    print(f"  去躁幅度       : {denoise_strength}")
    print(f"  VAE 名稱       : {vae_name}")
    print(f"  Checkpoint 名稱: {ckpt_name}")
    print(f"  隨機種子       : {seed}")
    print(f"  提示詞         : {prompt_text}")

    # 載入工作流程模板
    workflow_template = r"""
{
  "1": {"inputs":{"ckpt_name":"meinamix_v12Final.safetensors"},"class_type":"CheckpointLoaderSimple"},
  "2": {"inputs":{"text":"a girl","clip":["1",1]},"class_type":"CLIPTextEncode"},
  "3": {"inputs":{"text":"(low quality...)","clip":["1",1]},"class_type":"CLIPTextEncode"},
  "4": {"inputs":{"seed":0,"steps":20,"cfg":7,"sampler_name":"dpmpp_2m_sde","scheduler":"karras","denoise":0.7,"model":["1",0],"positive":["2",0],"negative":["3",0],"latent_image":["14",0]},"class_type":"KSampler"},
  "7": {"inputs":{"filename_prefix":"ComfyUI","images":["8",0]},"class_type":"SaveImage"},
  "8": {"inputs":{"samples":["4",0],"vae":["9",0]},"class_type":"VAEDecode"},
  "9": {"inputs":{"vae_name":"kl-f8-anime2.safetensors"},"class_type":"VAELoader"},
  "13":{"inputs":{"pixels":["17",0],"vae":["9",0]},"class_type":"VAEEncode"},
  "14":{"inputs":{"upscale_method":"nearest-exact","width":512,"height":512,"crop":"disabled","samples":["13",0]},"class_type":"LatentUpscale"},
  "17":{"inputs":{"image":"","force_size":"Disabled","custom_width":512,"custom_height":512},"class_type":"VHS_LoadImagePath"}
}
""".strip()

    workflow = json.loads(workflow_template)

    # 套用使用者參數
    workflow["1"]["inputs"]["ckpt_name"]     = ckpt_name
    workflow["9"]["inputs"]["vae_name"]      = vae_name
    workflow["2"]["inputs"]["text"]          = prompt_text or workflow["2"]["inputs"]["text"]
    workflow["4"]["inputs"]["cfg"]           = cfg_scale
    workflow["4"]["inputs"]["sampler_name"]  = sampler_name
    workflow["4"]["inputs"]["scheduler"]     = scheduler
    workflow["4"]["inputs"]["denoise"]       = denoise_strength
    workflow["4"]["inputs"]["seed"]          = seed
    workflow["17"]["inputs"]["image"]        = input_path.replace("\\", "/")

    print("🚀 發送 workflow 至 ComfyUI：")
    print(json.dumps(workflow, indent=2, ensure_ascii=False))

    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無法回應"}), 500

    prompt_id = resp["prompt_id"]
    client_id = resp["client_id"]

    wait_for_completion(prompt_id, client_id)

    fn = move_output_files(prompt_id)
    if not fn:
        return jsonify({"error": "圖片搬移失敗"}), 500

    image_url = f"{EXTERNAL_URL}/get_image/{fn}?t={int(time.time())}"
    return jsonify({"image_url": image_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    return send_from_directory(target_dir, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
