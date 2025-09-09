#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import uuid
import json
import base64
import shutil
import io
import urllib.request
import websocket  # pip install websocket-client
from PIL import Image
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address     = "127.0.0.1:8188"
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
temp_input_dir     = r"D:\大模型局部重繪\temp_input"
target_dir_redraw  = r"D:\大模型局部重繪"
EXTERNAL_URL       = "https://inpant.picturesmagician.com"

for d in (temp_input_dir, target_dir_redraw):
    os.makedirs(d, exist_ok=True)

# =============================
# 重繪專用 ComfyUI Workflow JSON
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
      "text": "",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "CLIP 文本编码器"}
  },
  "3": {
    "inputs": {
      "text": "",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "CLIP 文本编码器（负向）"}
  },
  "4": {
    "inputs": {
      "seed": 0,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1.0,
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["3", 0],
      "latent_image": ["13", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "K 取样器"}
  },
  "7": {
    "inputs": {
      "filename_prefix": "Redraw",
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
    "_meta": {"title": "VAE 解码"}
  },
  "9": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {"title": "VAE 加载器"}
  },
  "13": {
    "inputs": {
      "pixels": ["28", 0],
      "vae": ["9", 0]
    },
    "class_type": "VAEEncode",
    "_meta": {"title": "VAE 编码（空/原图）"}
  },
  "19": {
    "inputs": {
      "control_net_name": "control_sd15_canny.pth"
    },
    "class_type": "ControlNetLoader",
    "_meta": {"title": "ControlNet 加载器"}
  },
  "20": {
    "inputs": {
      "low_threshold": 100,
      "high_threshold": 200,
      "resolution": 512,
      "image": ["29", 0]
    },
    "class_type": "CannyEdgePreprocessor",
    "_meta": {"title": "Canny 预处理"}
  },
  "21": {
    "inputs": {
      "strength": 1.0,
      "start_percent": 0,
      "end_percent": 1,
      "positive": ["2", 0],
      "negative": ["3", 0],
      "control_net": ["19", 0],
      "image": ["20", 0],
      "vae": ["9", 0]
    },
    "class_type": "ControlNetApplyAdvanced",
    "_meta": {"title": "ControlNet 应用(进阶)"}
  },
  "26": {
    "inputs": {
      "images": ["29", 0]
    },
    "class_type": "PreviewImage",
    "_meta": {"title": "预览遮罩"}
  },
  "27": {
    "inputs": {
      "images": ["28", 0]
    },
    "class_type": "PreviewImage",
    "_meta": {"title": "预览原图"}
  },
  "28": {
    "inputs": {
      "image_path": ""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load 原图"}
  },
  "29": {
    "inputs": {
      "image_path": ""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {"title": "Load 遮罩图"}
  }
}
"""

# =============================
# 保存並縮放前端傳來的 Base64 圖片
# =============================
def save_base64_image(data_url, folder, prefix):
    try:
        header, encoded = data_url.split(",", 1)
    except Exception:
        return None, "無效的圖片資料"
    ext = "png" if "png" in header else "jpg"
    raw = base64.b64decode(encoded)
    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    img = img.resize((512, 512), Image.LANCZOS)
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    path = os.path.join(folder, filename)
    img.save(path)
    return path, None

# =============================
# 排隊到 ComfyUI
# =============================
def queue_prompt(workflow):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": workflow, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{server_address}/prompt",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    result["client_id"] = client_id
    return result

# =============================
# 等待 ComfyUI 完成
# =============================
def wait_for_completion(prompt_id, client_id):
    ws = websocket.create_connection(f"ws://{server_address}/ws?clientId={client_id}")
    while True:
        out = ws.recv()
        if isinstance(out, (bytes, bytearray)):
            try:
                out = out.decode("utf-8")
            except Exception:
                out = out.decode("latin-1", "ignore")
        try:
            msg = json.loads(out)
        except Exception:
            # 非 JSON 訊息（如 ping/pong）忽略
            continue
        if msg.get("type") == "executing":
            data = msg.get("data", {})
            if data.get("prompt_id") == prompt_id and data.get("node") is None:
                break
    ws.close()

# =============================
# 取得 & 搬移結果檔案
# =============================
def find_latest_png(directory):
    pngs = []
    for root, _, files in os.walk(directory):
        for fn in files:
            if fn.lower().endswith(".png"):
                pngs.append((os.path.getctime(os.path.join(root, fn)), fn))
    return max(pngs, key=lambda x: x[0])[1] if pngs else None

def get_final_image_filename(prompt_id):
    url = f"http://{server_address}/history/{prompt_id}"
    with urllib.request.urlopen(url) as resp:
        hist = json.loads(resp.read().decode("utf-8")).get(prompt_id, {})
    for nid in ("7",):
        for info in hist.get("outputs", {}).get(nid, {}).get("images", []):
            fn = info.get("filename")
            if fn and fn.lower().endswith(".png"):
                return fn
    return find_latest_png(comfyui_output_dir)

def move_output_files(prompt_id, target_dir):
    fn = get_final_image_filename(prompt_id)
    if not fn:
        raise FileNotFoundError("找不到輸出檔案")
    src = os.path.join(comfyui_output_dir, fn)
    if not os.path.exists(src):
        for root, _, files in os.walk(comfyui_output_dir):
            if fn in files:
                src = os.path.join(root, fn)
                break
    dst = os.path.join(target_dir, fn)
    shutil.move(src, dst)
    return fn

# =============================
# API Endpoint：/convert-image
# =============================
@app.route("/convert-image", methods=["POST"])
def convert_image_endpoint():
    data = request.get_json(force=True)
    print("▶ 收到參數：")
    for k in ("originalImage","maskImage","prompt","vaeName","checkpointName",
              "cfgScale","samplerName","scheduler","denoiseStrength","seed"):
        print(f"  {k}: {data.get(k)}")

    if not data.get("originalImage") or not data.get("maskImage"):
        return jsonify({"error":"缺少原圖或遮罩圖"}), 400

    orig_path, err = save_base64_image(data["originalImage"], temp_input_dir, "orig")
    if err: return jsonify({"error": err}), 400
    mask_path, err = save_base64_image(data["maskImage"],   temp_input_dir, "mask")
    if err: return jsonify({"error": err}), 400

    prompt_text  = data.get("prompt","").strip()
    vae_name     = data.get("vaeName","kl-f8-anime2.safetensors")
    ckpt_name    = data.get("checkpointName","meinamix_v12Final.safetensors")
    try:    cfg_scale = int(data.get("cfgScale",7))
    except: cfg_scale = 7
    sampler_name = data.get("samplerName","euler")
    scheduler    = data.get("scheduler","normal")
    try:    denoise = float(data.get("denoiseStrength",1.0))
    except: denoise = 1.0
    sv = data.get("seed","")
    try:    seed = int(sv) if sv else int(uuid.uuid4().int % 1000000)
    except: seed = int(uuid.uuid4().int % 1000000)

    if not prompt_text:
        return jsonify({"error":"提示詞為空"}), 400

    wf = json.loads(workflow_redraw_template)
    wf["1"]["inputs"]["ckpt_name"]    = ckpt_name
    wf["9"]["inputs"]["vae_name"]     = vae_name
    wf["2"]["inputs"]["text"]         = prompt_text
    wf["4"]["inputs"]["cfg"]          = cfg_scale
    wf["4"]["inputs"]["sampler_name"] = sampler_name
    wf["4"]["inputs"]["scheduler"]    = scheduler
    wf["4"]["inputs"]["denoise"]      = denoise
    wf["4"]["inputs"]["seed"]         = seed
    wf["28"]["inputs"]["image_path"]  = orig_path
    wf["29"]["inputs"]["image_path"]  = mask_path

    print("🚀 發送工作流程至 ComfyUI：")
    print(json.dumps(wf, indent=2, ensure_ascii=False))

    resp = queue_prompt(wf)
    pid, cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid, cid)
    time.sleep(2)
    fn = move_output_files(pid, target_dir_redraw)

    url = f"{EXTERNAL_URL}/get_image/{fn}?t={int(time.time())}"
    return jsonify({"image_url": url})

# =============================
# 圖片代理 Endpoint
# =============================
@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    p = os.path.join(target_dir_redraw, filename)
    if os.path.exists(p):
        return send_from_directory(target_dir_redraw, filename)
    return "檔案不存在", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
