#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import shutil
import time
import uuid
import base64
import urllib.request
import websocket  # pip install websocket-client
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------------------
# 檢查點到 ControlNet 的對應表
# ----------------------------
CHECKPOINT_TO_CONTROLNET = {
    "anythingelseV4_v45.safetensors":                "sd1.5_lineart.safetensors",
    "meinamix_v12Final.safetensors":                 "sd1.5_lineart.safetensors",
    "sdxlUnstableDiffusers_nihilmania.safetensors":  "sdxl_canny.safetensors",
    "sdxlYamersRealistic5_v5Rundiffusion.safetensor": "sdxl_canny.safetensors",
}
DEFAULT_CONTROLNET = "control_sd15_canny.pth"

# ----------------------------
# 文生模式 Workflow JSON (含 LoRA 節點)
# ----------------------------
text_workflow_json = r"""
{
  "1": {
    "inputs": { "ckpt_name": "meinamix_v12Final.safetensors" },
    "class_type": "CheckpointLoaderSimple",
    "_meta": { "title": "Checkpoint載入器(簡易)" }
  },
  "2": {
    "inputs": {
      "text": "example positive prompt",
      "clip": ["52", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": { "title": "CLIP文本編碼器" }
  },
  "3": {
    "inputs": {
      "text": "example negative prompt",
      "clip": ["52", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": { "title": "CLIP文本編碼器" }
  },
  "18": {
    "inputs": {
      "strength": 1.5,
      "start_percent": 0,
      "end_percent": 1,
      "positive": ["2", 0],
      "negative": ["3", 0],
      "control_net": ["19", 0],
      "image": ["47", 0],
      "vae": ["9", 0]
    },
    "class_type": "ControlNetApplyAdvanced",
    "_meta": { "title": "ControlNet應用(進階)" }
  },
  "19": {
    "inputs": { "control_net_name": "control_sd15_canny.pth" },
    "class_type": "ControlNetLoader",
    "_meta": { "title": "ControlNet載入器" }
  },
  "47": {
    "inputs": {
      "low_threshold": 100,
      "high_threshold": 200,
      "resolution": 512,
      "image": ["49", 0]
    },
    "class_type": "CannyEdgePreprocessor",
    "_meta": { "title": "Canny線條預處理器" }
  },
  "48": {
    "inputs": {
      "width": 512,
      "height": 512,
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage",
    "_meta": { "title": "空Latent" }
  },
  "49": {
    "inputs": { "image_path": "" },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": { "title": "Load 線稿圖(文生)" }
  },
  "50": {
    "inputs": { "images": ["49", 0] },
    "class_type": "PreviewImage",
    "_meta": { "title": "預覽線稿" }
  },
  "52": {
    "inputs": {
      "lora_name":        "asuna_(stacia)-v1.5.safetensors",
      "strength_model":   1,
      "strength_clip":    1,
      "model":            ["1", 0],
      "clip":             ["1", 1]
    },
    "class_type": "LoraLoader",
    "_meta": { "title": "LoRA載入器" }
  },
  "4": {
    "inputs": {
      "seed":        0,
      "steps":       20,
      "cfg":         7,
      "sampler_name":"euler",
      "scheduler":   "normal",
      "denoise":     1,
      "model":       ["52", 0],
      "positive":    ["18", 0],
      "negative":    ["18", 1],
      "latent_image":["48", 0]
    },
    "class_type": "KSampler",
    "_meta": { "title": "K採樣器" }
  },
  "8": {
    "inputs": {
      "samples": ["4", 0],
      "vae":     ["9", 0]
    },
    "class_type": "VAEDecode",
    "_meta": { "title": "VAE解碼" }
  },
  "7": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images":          ["8", 0]
    },
    "class_type": "SaveImage",
    "_meta": { "title": "儲存圖像" }
  },
  "9": {
    "inputs": { "vae_name": "kl-f8-anime2.safetensors" },
    "class_type": "VAELoader",
    "_meta": { "title": "VAE載入器" }
  }
}
"""

# ----------------------------
# 圖生模式 Workflow JSON (含 LoRA 節點)
# ----------------------------
image_workflow_json = r"""
{
  "1": {
    "inputs": { "ckpt_name": "meinamix_v12Final.safetensors" },
    "class_type": "CheckpointLoaderSimple",
    "_meta": { "title": "Checkpoint載入器(簡易)" }
  },
  "2": {
    "inputs": {
      "text": "example positive prompt",
      "clip": ["52", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": { "title": "CLIP文本編碼器" }
  },
  "3": {
    "inputs": {
      "text": "example negative prompt",
      "clip": ["52", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": { "title": "CLIP文本編碼器" }
  },
  "18": {
    "inputs": {
      "strength":      1.5,
      "start_percent": 0,
      "end_percent":   1,
      "positive":      ["2", 0],
      "negative":      ["3", 0],
      "control_net":   ["19", 0],
      "image":         ["47", 0],
      "vae":           ["9", 0]
    },
    "class_type": "ControlNetApplyAdvanced",
    "_meta": { "title": "ControlNet應用(進階)" }
  },
  "19": {
    "inputs": { "control_net_name": "control_sd15_canny.pth" },
    "class_type": "ControlNetLoader",
    "_meta": { "title": "ControlNet載入器" }
  },
  "47": {
    "inputs": {
      "low_threshold": 100,
      "high_threshold":200,
      "resolution":    512,
      "image":         ["49", 0]
    },
    "class_type": "CannyEdgePreprocessor",
    "_meta": { "title": "Canny線條預處理器" }
  },
  "48": {
    "inputs": { "image_path": "" },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": { "title": "Load 輔助線稿圖(圖生)" }
  },
  "51": {
    "inputs": { "image_path": "" },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": { "title": "Load 主線稿圖(圖生)" }
  },
  "52": {
    "inputs": {
      "lora_name":        "asuna_(stacia)-v1.5.safetensors",
      "strength_model":   1,
      "strength_clip":    1,
      "model":            ["1", 0],
      "clip":             ["1", 1]
    },
    "class_type": "LoraLoader",
    "_meta": { "title": "LoRA載入器" }
  },
  "4": {
    "inputs": {
      "seed":        0,
      "steps":       20,
      "cfg":         7,
      "sampler_name":"euler",
      "scheduler":   "normal",
      "denoise":     1,
      "model":       ["52", 0],
      "positive":    ["18", 0],
      "negative":    ["18", 1],
      "latent_image":["48", 0]
    },
    "class_type": "KSampler",
    "_meta": { "title": "K採樣器" }
  },
  "8": {
    "inputs": {
      "samples": ["4", 0],
      "vae":     ["9", 0]
    },
    "class_type": "VAEDecode",
    "_meta": { "title": "VAE解碼" }
  },
  "7": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images":          ["8", 0]
    },
    "class_type": "SaveImage",
    "_meta": { "title": "儲存圖像" }
  },
  "9": {
    "inputs": { "vae_name": "kl-f8-anime2.safetensors" },
    "class_type": "VAELoader",
    "_meta": { "title": "VAE載入器" }
  }
}
"""

# ----------------------------
# ComfyUI 伺服器與資料夾設定
# ----------------------------
server_address     = "127.0.0.1:8188"
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir_text    = r"D:\大模型文生線稿上色圖"
target_dir_image   = r"D:\大模型圖生線稿上色圖"
TEMP_IMAGE_DIR     = r"D:\comfyui\temp_images"
EXTERNAL_API_URL   = "https://linecolor-lora.picturesmagician.com"

for d in (target_dir_text, target_dir_image, TEMP_IMAGE_DIR):
    os.makedirs(d, exist_ok=True)

# ----------------------------
# 輔助函式
# ----------------------------
def queue_prompt(workflow_dict):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": workflow_dict, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{server_address}/prompt",
        data=data,
        headers={"Content-Type":"application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        result["client_id"] = client_id
        return result

def wait_for_completion(prompt_id, client_id):
    ws = websocket.create_connection(f"ws://{server_address}/ws?clientId={client_id}", timeout=60)
    while True:
        msg = ws.recv()
        m = json.loads(msg) if isinstance(msg, str) else {}
        if m.get("type") == "executing":
            d = m.get("data", {})
            if d.get("prompt_id") == prompt_id and d.get("node") is None:
                break
    ws.close()

def find_latest_png(directory):
    pngs = [f for f in os.listdir(directory) if f.lower().endswith(".png")]
    return max(pngs, key=lambda fn: os.path.getctime(os.path.join(directory, fn))) if pngs else None

def get_final_image_filename(prompt_id):
    url = f"http://{server_address}/history/{prompt_id}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        hist = json.loads(resp.read().decode("utf-8")).get(prompt_id, {})
    for nid in ("7",):
        for info in hist.get("outputs", {}).get(nid, {}).get("images", []):
            fn = info.get("filename")
            if fn and fn.lower().endswith(".png"):
                return fn
    return find_latest_png(comfyui_output_dir)

def move_output_files(prompt_id, target_folder):
    fn = get_final_image_filename(prompt_id)
    if not fn:
        return None
    src = os.path.join(comfyui_output_dir, fn)
    suffix = prompt_id.replace("-", "")[:8]
    new_fn = f"{suffix}_{fn}"
    dst = os.path.join(target_folder, new_fn)
    shutil.move(src, dst)
    return new_fn

def apply_cn(workflow, cn):
    if "18" in workflow:
        inp = workflow["18"]["inputs"]
        inp["strength"]      = float(cn.get("strength", 1.5))
        inp["start_percent"] = float(cn.get("start_percent", 0.0))
        inp["end_percent"]   = float(cn.get("end_percent", 1.0))
    return workflow

# ----------------------------
# 文生模式路由
# ----------------------------
@app.route("/lineart_color_text", methods=["POST"])
def lineart_color_text():
    data = request.get_json()
    print("Received /lineart_color_text parameters:")
    for k, v in data.items():
        print(f"  {k}: {v}")

    # 驗證
    if not data or "prompt" not in data:
        return jsonify({"error":"缺少提示詞"}), 400

    # 解碼並存檔線稿圖
    try:
        b64 = data["line_art_image"].split(",", 1)[1]
        img = base64.b64decode(b64)
        fn  = f"lineart_{uuid.uuid4().hex}.png"
        path= os.path.join(TEMP_IMAGE_DIR, fn)
        with open(path, "wb") as f:
            f.write(img)
        data["line_art_image"] = path
    except Exception as e:
        return jsonify({"error":f"線稿圖解碼失敗: {e}"}), 400

    # 準備 workflow
    wf = json.loads(text_workflow_json)

    # apply checkpoint / vae
    if data.get("ckpt_name"):
        wf["1"]["inputs"]["ckpt_name"] = data["ckpt_name"]
    if data.get("vae_name"):
        wf["9"]["inputs"]["vae_name"] = data["vae_name"]

    # apply LoRA
    if data.get("lora_name"):
        wf["52"]["inputs"]["lora_name"]      = data["lora_name"]
        wf["52"]["inputs"]["strength_model"] = float(data.get("strength_model", 1.0))
        wf["52"]["inputs"]["strength_clip"]  = float(data.get("strength_clip", 1.0))

    # 文字與採樣參數
    wf["2"]["inputs"]["text"]            = data["prompt"]
    wf["4"]["inputs"]["cfg"]             = int(data.get("cfg_scale", 7))
    wf["4"]["inputs"]["sampler_name"]    = data.get("sampler", "euler")
    wf["4"]["inputs"]["scheduler"]       = data.get("scheduler", "normal")
    wf["4"]["inputs"]["seed"]            = int(data.get("seed", 0))
    wf["4"]["inputs"]["denoise"]         = float(data.get("denoise_strength", 1.0))
    wf["47"]["inputs"]["low_threshold"]  = int(data.get("low_threshold", 100))
    wf["47"]["inputs"]["high_threshold"] = int(data.get("high_threshold", 200))
    wf["49"]["inputs"]["image_path"]     = data["line_art_image"]

    # ControlNet 參數
    if data.get("control_net_params"):
        wf = apply_cn(wf, data["control_net_params"])

    # 自動對應 ControlNet 檔名
    selected_ckpt = data.get("ckpt_name", "")
    cn_name = CHECKPOINT_TO_CONTROLNET.get(selected_ckpt, DEFAULT_CONTROLNET)
    wf["19"]["inputs"]["control_net_name"] = cn_name

    print("🚀 文生模式發送中…")
    resp = queue_prompt(wf)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error":"ComfyUI 回應異常"}), 500

    pid, cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid, cid)
    fn = move_output_files(pid, target_dir_text)
    if not fn:
        return jsonify({"error":"搬檔失敗"}), 500

    url = f"{EXTERNAL_API_URL}/get_image/{fn}?t={int(time.time())}"
    return jsonify({"image_url": url})

# ----------------------------
# 圖生模式路由
# ----------------------------
@app.route("/lineart_color_image", methods=["POST"])
def lineart_color_image():
    data = request.get_json()
    print("Received /lineart_color_image parameters:")
    for k, v in data.items():
        print(f"  {k}: {v}")

    # 驗證
    if not data or "prompt" not in data or "image" not in data:
        return jsonify({"error":"缺少提示詞或主圖"}), 400

    # 解碼並存檔主圖
    try:
        b64 = data["image"].split(",", 1)[1]
        img = base64.b64decode(b64)
        fn  = f"main_{uuid.uuid4().hex}.png"
        path= os.path.join(TEMP_IMAGE_DIR, fn)
        with open(path, "wb") as f:
            f.write(img)
        data["image"] = path
    except Exception as e:
        return jsonify({"error":f"主圖解碼失敗: {e}"}), 400

    # 解碼並存檔輔助線稿（可空）
    if data.get("line_art_image"):
        try:
            b64 = data["line_art_image"].split(",", 1)[1]
            img = base64.b64decode(b64)
            fn  = f"aux_{uuid.uuid4().hex}.png"
            ap  = os.path.join(TEMP_IMAGE_DIR, fn)
            with open(ap, "wb") as f:
                f.write(img)
            data["line_art_image"] = ap
        except Exception as e:
            return jsonify({"error":f"輔助線稿解碼失敗: {e}"}), 400
    else:
        data["line_art_image"] = data["image"]

    # 準備 workflow
    wf = json.loads(image_workflow_json)

    # apply checkpoint / vae
    if data.get("ckpt_name"):
        wf["1"]["inputs"]["ckpt_name"] = data["ckpt_name"]
    if data.get("vae_name"):
        wf["9"]["inputs"]["vae_name"]  = data["vae_name"]

    # apply LoRA
    if data.get("lora_name"):
        wf["52"]["inputs"]["lora_name"]      = data["lora_name"]
        wf["52"]["inputs"]["strength_model"] = float(data.get("strength_model", 1.0))
        wf["52"]["inputs"]["strength_clip"]  = float(data.get("strength_clip", 1.0))

    # 文字與採樣參數
    wf["2"]["inputs"]["text"]            = data["prompt"]
    wf["4"]["inputs"]["cfg"]             = int(data.get("cfg_scale", 7))
    wf["4"]["inputs"]["sampler_name"]    = data.get("sampler", "euler")
    wf["4"]["inputs"]["scheduler"]       = data.get("scheduler", "normal")
    wf["4"]["inputs"]["seed"]            = int(data.get("seed", 0))
    wf["4"]["inputs"]["denoise"]         = float(data.get("denoise_strength", 1.0))
    wf["47"]["inputs"]["low_threshold"]  = int(data.get("low_threshold", 100))
    wf["47"]["inputs"]["high_threshold"] = int(data.get("high_threshold", 200))
    wf["49"]["inputs"]["image_path"]     = data["line_art_image"]
    wf["51"]["inputs"]["image_path"]     = data["image"]

    # ControlNet 參數
    if data.get("control_net_params"):
        wf = apply_cn(wf, data["control_net_params"])

    # 自動對應 ControlNet 檔名
    selected_ckpt = data.get("ckpt_name", "")
    cn_name = CHECKPOINT_TO_CONTROLNET.get(selected_ckpt, DEFAULT_CONTROLNET)
    wf["19"]["inputs"]["control_net_name"] = cn_name

    print("🚀 圖生模式發送中…")
    resp = queue_prompt(wf)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error":"ComfyUI 回應異常"}), 500

    pid, cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid, cid)
    fn = move_output_files(pid, target_dir_image)
    if not fn:
        return jsonify({"error":"搬檔失敗"}), 500

    url = f"{EXTERNAL_API_URL}/get_image/{fn}?t={int(time.time())}"
    return jsonify({"image_url": url})

# ----------------------------
# 圖片代理 API & 啟動服務
# ----------------------------
@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    t = os.path.join(target_dir_text, filename)
    i = os.path.join(target_dir_image, filename)
    if os.path.exists(t):
        resp = make_response(send_from_directory(target_dir_text, filename))
    elif os.path.exists(i):
        resp = make_response(send_from_directory(target_dir_image, filename))
    else:
        return jsonify({"error":"檔案不存在"}), 404
    resp.headers.update({
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache"
    })
    return resp

if __name__ == "__main__":
    # 開發測試用，正式部署請改用 gunicorn/uwsgi
    app.run(host="0.0.0.0", port=5017, debug=False)
