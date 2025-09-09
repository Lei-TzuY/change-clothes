import os
import time
import uuid
import json
import base64
import shutil
import urllib.request
import urllib.error
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
EXTERNAL_URL         = "https://inpant.picturesmagician.com"

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
  "26": {
    "inputs": {
      "images": ["29", 0]
    },
    "class_type": "PreviewImage",
    "_meta": {"title": "预览图像"}
  },
  "27": {
    "inputs": {
      "images": ["28", 0]
    },
    "class_type": "PreviewImage",
    "_meta": {"title": "预览图像"}
  },
  "28": {
    "inputs": {
      "image_path": ""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  },
  "29": {
    "inputs": {
      "image_path": ""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  }
}
""".strip()

workflow_reverse_template = r"""
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
      "pixels": ["25", 0],
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
      "image": ["26", 0]
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
  "25": {
    "inputs": {
      "image_path": ""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  },
  "26": {
    "inputs": {
      "image_path": ""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load Image Path or URL"}
  },
  "27": {
    "inputs": {
      "images": ["25", 0]
    },
    "class_type": "PreviewImage",
    "_meta": {"title": "预览图像"}
  }
}
""".strip()

# =============================
# 工具函數：保存 Base64 圖片
# =============================
def save_base64_image(data_url, folder, prefix):
    try:
        header, encoded = data_url.split(",", 1)
    except:
        return None, "無效的圖片資料"
    ext = "png" if "png" in header else "jpg"
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(base64.b64decode(encoded))
    return path, None

# =============================
# 工具函數：ComfyUI 互動
# =============================
def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": prompt, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{server_address}/prompt",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    result["client_id"] = client_id
    return result

def wait_for_completion(prompt_id, client_id):
    ws = websocket.create_connection(f"ws://{server_address}/ws?clientId={client_id}")
    while True:
        out = ws.recv()
        msg = json.loads(out)
        if msg.get("type") == "executing":
            data = msg.get("data", {})
            if data.get("node") is None and data.get("prompt_id") == prompt_id:
                break
    ws.close()

def get_history(prompt_id):
    with urllib.request.urlopen(f"http://{server_address}/history/{prompt_id}") as resp:
        history = json.loads(resp.read())
    return history.get(prompt_id, {})

def find_latest_png():
    files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    return max(files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f))) if files else None

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    outputs = history.get("outputs", {})
    for node_key in ("27","7"):
        node = outputs.get(node_key, {})
        for info in node.get("images", []):
            fn = info.get("filename")
            if fn and fn.lower().endswith(".png"):
                return fn
    return find_latest_png()

def move_output_files(prompt_id, target_dir):
    fn = get_final_image_filename(prompt_id)
    src = os.path.join(comfyui_output_dir, fn)
    dst = os.path.join(target_dir, fn)
    shutil.move(src, dst)
    return fn

# =============================
# API Endpoint：/convert-image
# =============================
@app.route("/convert-image", methods=["POST"])
def convert_image_endpoint():
    data = request.get_json(force=True)

    # —— 修改處：列印所有前端傳來的參數 ——  
    print("▶ 收到參數：")
    print(f"  originalImage   : {bool(data.get('originalImage'))}")
    print(f"  maskImage       : {bool(data.get('maskImage'))}")
    print(f"  purePainting    : {bool(data.get('purePainting'))}")
    print(f"  prompt          : {data.get('prompt')}")
    print(f"  vaeName         : {data.get('vaeName')}")
    print(f"  checkpointName  : {data.get('checkpointName')}")
    print(f"  cfgScale        : {data.get('cfgScale')}")
    print(f"  samplerName     : {data.get('samplerName')}")
    print(f"  scheduler       : {data.get('scheduler')}")
    print(f"  denoiseStrength : {data.get('denoiseStrength')}")
    print(f"  seed            : {data.get('seed')}")
    print(f"  mode            : {data.get('mode')}")

    if not data.get("originalImage") or not data.get("maskImage"):
        return jsonify({"error": "未提供原始圖片或遮罩圖片"}), 400

    orig_path, err = save_base64_image(data["originalImage"], temp_input_dir, "orig")
    mask_path, err = save_base64_image(data["maskImage"], temp_input_dir, "mask")

    pure_path = None
    if data.get("purePainting"):
        pure_path, err = save_base64_image(data["purePainting"], temp_input_dir, "pure")

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
        seed          = int(seed_val) if seed_val != "" else int(uuid.uuid4().int % 1000000)
    except:
        seed          = int(uuid.uuid4().int % 1000000)

    if not prompt_text:
        return jsonify({"error": "提示詞為空"}), 400

    mode = (data.get("mode") or "redraw").strip()
    if mode == "reverse":
        workflow_template = workflow_reverse_template
        target_dir        = target_dir_reverse
    else:
        workflow_template = workflow_redraw_template
        target_dir        = target_dir_redraw

    workflow = json.loads(workflow_template)

    # —— 修改處：注入所有參數到工作流程 ——  
    workflow["1"]["inputs"]["ckpt_name"]    = ckpt_name
    workflow["9"]["inputs"]["vae_name"]     = vae_name
    workflow["2"]["inputs"]["text"]         = prompt_text
    workflow["4"]["inputs"]["cfg"]          = cfg_scale
    workflow["4"]["inputs"]["sampler_name"] = sampler_name
    workflow["4"]["inputs"]["scheduler"]    = scheduler
    workflow["4"]["inputs"]["denoise"]      = denoise_strength
    workflow["4"]["inputs"]["seed"]         = seed
    if mode == "reverse":
        workflow["25"]["inputs"]["image_path"] = orig_path
        workflow["26"]["inputs"]["image_path"] = mask_path
    else:
        workflow["28"]["inputs"]["image_path"] = orig_path
        workflow["29"]["inputs"]["image_path"] = mask_path

    print("🚀 發送工作流程至 ComfyUI：")
    print(json.dumps(workflow, indent=4, ensure_ascii=False))

    resp      = queue_prompt(workflow)
    prompt_id = resp["prompt_id"]
    client_id = resp["client_id"]
    wait_for_completion(prompt_id, client_id)

    time.sleep(5)  # 確保檔案已生成
    output_fn = move_output_files(prompt_id, target_dir)
    image_url  = EXTERNAL_URL + "/get_image/" + output_fn + f"?t={int(time.time())}"
    pure_url   = None

    if pure_path:
        pure_fn      = os.path.basename(pure_path)
        shutil.copy(pure_path, os.path.join(pure_painting_dir, pure_fn))
        pure_url     = EXTERNAL_URL + "/get_pure/" + pure_fn + f"?t={int(time.time())}"

    return jsonify({"image_url": image_url, "pure_painting_url": pure_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    for d in (target_dir_redraw, target_dir_reverse):
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return send_from_directory(d, filename)
    return "檔案不存在", 404

@app.route("/get_pure/<filename>", methods=["GET"])
def get_pure(filename):
    p = os.path.join(pure_painting_dir, filename)
    if os.path.exists(p):
        return send_from_directory(pure_painting_dir, filename)
    return "檔案不存在", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
