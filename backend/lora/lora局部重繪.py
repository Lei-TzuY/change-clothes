import os
import time
import uuid
import json
import base64
import shutil
import urllib.request
import websocket

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address       = "127.0.0.1:8188"  # ComfyUI 伺服器位址
comfyui_output_dir   = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
temp_input_dir       = r"D:\大模型局部重繪\temp_input"
os.makedirs(temp_input_dir, exist_ok=True)

target_dir_redraw    = r"D:\大模型局部重繪"
target_dir_reverse   = r"D:\大模型局部重繪反轉"
os.makedirs(target_dir_redraw, exist_ok=True)
os.makedirs(target_dir_reverse, exist_ok=True)

pure_painting_dir    = r"D:\大模型局部重繪\pure_painting"
os.makedirs(pure_painting_dir, exist_ok=True)

# 外網域名
EXTERNAL_URL         = "https://inpant-lora.picturesmagician.com"

# =============================
# 工作流程模板（保持原樣）
# =============================
workflow_redraw_template = r"""
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
      "text": "default",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "正向提示词"}
  },
  "3": {
    "inputs": {
      "text": "negative prompt",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "反向提示词"}
  },
  "4": {
    "inputs": {
      "seed": 0,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "euler",
      "scheduler": "karras",
      "denoise": 1,
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
  "13": {
    "inputs": {
      "pixels": ["28", 0],
      "vae": ["9", 0]
    },
    "class_type": "VAEEncode",
    "_meta": {"title": "VAE编码"}
  },
  "14": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 512,
      "height": 512,
      "crop": "disabled",
      "samples": ["15", 0]
    },
    "class_type": "LatentUpscale",
    "_meta": {"title": "缩放Latent"}
  },
  "15": {
    "inputs": {
      "samples": ["21", 0],
      "mask": ["19", 0]
    },
    "class_type": "SetLatentNoiseMask",
    "_meta": {"title": "设置Latent噪声遮罩"}
  },
  "19": {
    "inputs": {
      "channel": "red",
      "image": ["29", 0]
    },
    "class_type": "ImageToMask",
    "_meta": {"title": "图像到遮罩"}
  },
  "21": {
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
  "22": {
    "inputs": {
      "lora_name": "asuna_(stacia)-v1.5.safetensors",
      "strength_model": 1,
      "strength_clip": 1,
      "model": ["1", 0],
      "clip": ["1", 1]
    },
    "class_type": "LoraLoader",
    "_meta": {"title": "LoRA载入器"}
  },
  "23": {
    "inputs": {
      "image_path": "\"./input/example.png\""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  },
  "24": {
    "inputs": {
      "image_path": "\"./input/example.png\""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  },
  "25": {
    "inputs": {"image_path": ""},
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  },
  "26": {
    "inputs": {"image_path": ""},
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  }
}
""".strip()

workflow_reverse_template = r"""
# （反轉模板省略，與上方結構相同，僅節點編號不同）
""".strip()

# =============================
# 儲存 Base64 圖片
# =============================
def save_base64_image(data_url, folder, prefix):
    header, encoded = data_url.split(",", 1)
    ext = "png" if "png" in header else "jpg"
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(base64.b64decode(encoded))
    return path, None

# =============================
# 發送 ComfyUI 任務、等待完成、搬移檔案
# =============================
def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                msg = json.loads(out)
                if msg.get("type")=="executing" and msg.get("data",{}).get("node") is None \
                   and msg["data"].get("prompt_id")==prompt_id:
                    break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 錯誤: {e}")

def move_output_files(prompt_id, target_dir):
    # 同原本的檔案搬移
    ...

@app.route("/image_to_image", methods=["POST"])
def image_to_image():
    data = request.get_json()
    # —— 讀取與轉型參數 ——  
    orig_img = data.get("originalImage")
    mask_img = data.get("maskImage")
    pure_img = data.get("purePainting")

    prompt_text      = data.get("prompt", "").strip()
    vae_name         = data.get("vaeName", "kl-f8-anime2.safetensors")
    ckpt_name        = data.get("checkpointName", "meinamix_v12Final.safetensors")
    try:
        cfg_scale     = int(data.get("cfgScale", 7))
    except:
        cfg_scale     = 7
    sampler_name     = data.get("samplerName", "euler")
    scheduler        = data.get("scheduler", "karras")
    try:
        denoise_strength = float(data.get("denoiseStrength", 1.0))
    except:
        denoise_strength = 1.0
    seed_val         = data.get("seed", "")
    try:
        seed          = int(seed_val) if seed_val!="" else int(uuid.uuid4().int % 1000000)
    except:
        seed          = int(uuid.uuid4().int % 1000000)

    # —— 新增 LoRA 參數讀取 ——  
    lora_name        = data.get("loraName", "super-vanilla-newlora-ver1-p.safetensors")
    try:
        strength_model = float(data.get("loraStrengthModel", 0))
    except:
        strength_model = 0.0
    try:
        strength_clip  = float(data.get("loraStrengthClip", 1))
    except:
        strength_clip  = 1.0

    # —— 印出所有參數 ——  
    print("🔹 收到參數：")
    print(f"  originalImage   : {bool(orig_img)}")
    print(f"  maskImage       : {bool(mask_img)}")
    print(f"  purePainting    : {bool(pure_img)}")
    print(f"  prompt          : {prompt_text}")
    print(f"  vaeName         : {vae_name}")
    print(f"  checkpointName  : {ckpt_name}")
    print(f"  cfgScale        : {cfg_scale}")
    print(f"  samplerName     : {sampler_name}")
    print(f"  scheduler       : {scheduler}")
    print(f"  denoiseStrength : {denoise_strength}")
    print(f"  seed            : {seed}")
    print(f"  loraName        : {lora_name}")
    print(f"  loraStrengthModel: {strength_model}")
    print(f"  loraStrengthClip: {strength_clip}")

    if not orig_img or not mask_img:
        return jsonify({"error": "未提供原始圖片或遮罩圖片"}), 400

    # —— 存圖檔至暫存 ——  
    orig_path, _ = save_base64_image(orig_img, temp_input_dir, "orig")
    mask_path, _ = save_base64_image(mask_img, temp_input_dir, "mask")
    pure_path = None
    if pure_img:
        pure_path, _ = save_base64_image(pure_img, temp_input_dir, "pure")

    mode = data.get("mode","redraw").strip()
    if mode=="reverse":
        workflow_template = workflow_reverse_template
        target_dir        = target_dir_reverse
    else:
        workflow_template = workflow_redraw_template
        target_dir        = target_dir_redraw

    workflow = json.loads(workflow_template)

    # —— 注入基本參數 ——  
    workflow["1"]["inputs"]["ckpt_name"]    = ckpt_name
    workflow["9"]["inputs"]["vae_name"]     = vae_name
    workflow["2"]["inputs"]["text"]         = prompt_text
    workflow["4"]["inputs"]["cfg"]          = cfg_scale
    workflow["4"]["inputs"]["sampler_name"] = sampler_name
    workflow["4"]["inputs"]["scheduler"]    = scheduler
    workflow["4"]["inputs"]["denoise"]      = denoise_strength
    workflow["4"]["inputs"]["seed"]         = seed

    # —— 注入 LoRA 參數至「22」節點 ——  
    workflow["22"]["inputs"]["lora_name"]        = lora_name
    workflow["22"]["inputs"]["strength_model"]   = strength_model
    workflow["22"]["inputs"]["strength_clip"]    = strength_clip

    # —— 注入圖片路徑 ——  
    if mode=="reverse":
        workflow["25"]["inputs"]["image_path"] = orig_path
        workflow["26"]["inputs"]["image_path"] = mask_path
    else:
        workflow["28"]["inputs"]["image_path"] = orig_path
        workflow["29"]["inputs"]["image_path"] = mask_path

    # —— 發送並等待結果 ——  
    print("🚀 發送工作流程至 ComfyUI：")
    print(json.dumps(workflow, indent=4, ensure_ascii=False))
    resp      = queue_prompt(workflow)
    prompt_id = resp["prompt_id"]
    client_id = resp["client_id"]
    wait_for_completion(prompt_id, client_id)

    time.sleep(5)  # 確保圖片生成完成
    output_fn = move_output_files(prompt_id, target_dir)
    image_url  = EXTERNAL_URL + "/get_image/" + output_fn + f"?t={int(time.time())}"
    pure_url   = None
    if pure_path:
        fn = os.path.basename(pure_path)
        shutil.copy(pure_path, os.path.join(pure_painting_dir, fn))
        pure_url = EXTERNAL_URL + "/get_pure/" + fn + f"?t={int(time.time())}"

    return jsonify({"image_url": image_url, "pure_painting_url": pure_url})

@app.route("/get_image/<filename>")
def get_image(filename):
    return send_from_directory(target_dir_redraw if os.path.exists(os.path.join(target_dir_redraw, filename)) else target_dir_reverse, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5013)
