#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import shutil
import time
import uuid
import base64
import urllib.request
import websocket               # pip install websocket-client
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# -----------------------------------
# ComfyUI & 目錄設定
# -----------------------------------
server_address     = "127.0.0.1:8188"
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"

target_dir_text  = r"D:\大模型文生圖姿勢控制"
target_dir_image = r"D:\大模型圖生圖姿勢控制"
os.makedirs(target_dir_text, exist_ok=True)
os.makedirs(target_dir_image, exist_ok=True)

temp_dir = r"D:\大模型姿勢控制\temp_input"
os.makedirs(temp_dir, exist_ok=True)

EXTERNAL_API_URL = "https://pose-lora.picturesmagician.com"

# -----------------------------------
# Workflow JSON（文生模式）
# -----------------------------------
WORKFLOW_TEXT_BASE = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands...", "clip": ["1", 1]} },
  "4": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 87,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "dpmpp_2m_sde",
      "scheduler": "karras",
      "denoise": 1,
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["3", 0],
      "latent_image": ["47", 0]
    }
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["4", 0], "vae": ["9", 0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"}
  },
  "47": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width": 512, "height": 512, "batch_size": 1}
  }
}
""".strip()

WORKFLOW_TEXT_CN = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands...", "clip": ["1", 1]} },
  "4": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 87,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "dpmpp_2m_sde",
      "scheduler": "karras",
      "denoise": 1,
      "model": ["1", 0],
      "positive": ["23", 0],
      "negative": ["23", 1],
      "latent_image": ["47", 0]
    }
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["4", 0], "vae": ["9", 0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"}
  },
  "17": {
    "class_type": "OpenposePreprocessor",
    "inputs": {
      "detect_hand": "enable",
      "detect_body": "enable",
      "detect_face": "disable",
      "resolution": 512,
      "scale_stick_for_xinsr_cn": "disable",
      "image": ["48", 0]
    }
  },
  "18": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength": 1.2,
      "start_percent": 0,
      "end_percent": 1,
      "positive": ["2", 0],
      "negative": ["3", 0],
      "control_net": ["19", 0],
      "image": ["17", 0],
      "vae": ["9", 0]
    }
  },
  "19": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name": "control_sd15_openpose.pth"}
  },
  "23": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength": 1.0,
      "start_percent": 0,
      "end_percent": 1,
      "positive": ["18", 0],
      "negative": ["18", 1],
      "control_net": ["24", 0],
      "image": ["28", 0],
      "vae": ["9", 0]
    }
  },
  "24": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name": "control_sd15_depth.pth"}
  },
  "28": {
    "class_type": "MiDaS-DepthMapPreprocessor",
    "inputs": {
      "a": 0,
      "bg_threshold": 0.1,
      "resolution": 512,
      "image": ["50", 0]
    }
  },
  "48": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": "C:\\dummy_pose.png"}
  },
  "50": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": "C:\\dummy_pose.png"}
  },
  "47": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width": 512, "height": 512, "batch_size": 1}
  }
}
""".strip()

# -----------------------------------
# 工作流程 JSON（圖生模式 - 無 ControlNet / 有 ControlNet）
# TEXT 模式用 47 為 latent；IMAGE 模式改用 37 為 VAEEncode latent
# -----------------------------------
WORKFLOW_IMAGE_BASE = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands...", "clip": ["1", 1]} },
  "4": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 87,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "dpmpp_2m_sde",
      "scheduler": "karras",
      "denoise": 1,
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["3", 0],
      "latent_image": ["37", 0]
    }
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["4", 0], "vae": ["9", 0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"}
  },
  "37": {
    "class_type": "VAEEncode",
    "inputs": {"pixels": ["47", 0], "vae": ["9", 0]}
  },
  "47": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": "C:\\dummy_main.png"}
  }
}
""".strip()

WORKFLOW_IMAGE_CN = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands...", "clip": ["1", 1]} },
  "4": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 87,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "dpmpp_2m_sde",
      "scheduler": "karras",
      "denoise": 1,
      "model": ["1", 0],
      "positive": ["23", 0],
      "negative": ["23", 1],
      "latent_image": ["37", 0]
    }
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["4", 0], "vae": ["9", 0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"}
  },
  "17": {
    "class_type": "OpenposePreprocessor",
    "inputs": {
      "detect_hand": "enable",
      "detect_body": "enable",
      "detect_face": "disable",
      "resolution": 512,
      "scale_stick_for_xinsr_cn": "disable",
      "image": ["49", 0]
    }
  },
  "18": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength": 1.2,
      "start_percent": 0,
      "end_percent": 1,
      "positive": ["2", 0],
      "negative": ["3", 0],
      "control_net": ["19", 0],
      "image": ["17", 0],
      "vae": ["9", 0]
    }
  },
  "19": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name": "control_sd15_openpose.pth"}
  },
  "23": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength": 1.0,
      "start_percent": 0,
      "end_percent": 1,
      "positive": ["18", 0],
      "negative": ["18", 1],
      "control_net": ["24", 0],
      "image": ["28", 0],
      "vae": ["9", 0]
    }
  },
  "24": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name": "control_sd15_depth.pth"}
  },
  "28": {
    "class_type": "MiDaS-DepthMapPreprocessor",
    "inputs": {
      "a": 0,
      "bg_threshold": 0.1,
      "resolution": 512,
      "image": ["50", 0]
    }
  },
  "37": {
    "class_type": "VAEEncode",
    "inputs": {"pixels": ["47", 0], "vae": ["9", 0]}
  },
  "47": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": "C:\\dummy_main.png"}
  },
  "49": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": "C:\\dummy_pose.png"}
  },
  "50": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": "C:\\dummy_pose.png"}
  }
}
""".strip()
# -----------------------------------
# Helper functions
# -----------------------------------
def queue_prompt(wf):
    client_id = str(uuid.uuid4())
    payload = {"prompt": wf, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        result["client_id"] = client_id
        return result

def wait_for_completion(prompt_id, client_id):
    ws = websocket.create_connection(f"ws://{server_address}/ws?clientId={client_id}", timeout=60)
    while True:
        msg = ws.recv()
        m = json.loads(msg) if isinstance(msg, str) else {}
        if m.get("type")=="executing":
            d = m.get("data",{})
            if d.get("prompt_id")==prompt_id and d.get("node") is None:
                break
    ws.close()

def move_output_files(prompt_id, target_folder):
    pngs = [f for f in os.listdir(comfyui_output_dir) if f.startswith("ComfyUI_") and f.endswith(".png")]
    if not pngs:
        return None
    pngs.sort(key=lambda fn: os.path.getmtime(os.path.join(comfyui_output_dir, fn)), reverse=True)
    src = os.path.join(comfyui_output_dir, pngs[0])
    dst = os.path.join(target_folder, pngs[0])
    shutil.move(src, dst)
    return pngs[0]

def apply_controlnet_params_text_cn(wf, cn):
    # 姿勢
    if "17" in wf:
        for k in ("detect_hand","detect_body","detect_face"):
            wf["17"]["inputs"][k] = cn.get(k, wf["17"]["inputs"].get(k))
    if "18" in wf:
        wf["18"]["inputs"]["strength"]      = cn.get("strength", wf["18"]["inputs"]["strength"])
        wf["18"]["inputs"]["start_percent"] = cn.get("start_percent", wf["18"]["inputs"]["start_percent"])
        wf["18"]["inputs"]["end_percent"]   = cn.get("end_percent", wf["18"]["inputs"]["end_percent"])
    # 深度
    if "28" in wf:
        wf["28"]["inputs"]["a"]            = cn.get("depth_angle", wf["28"]["inputs"]["a"])
        wf["28"]["inputs"]["bg_threshold"] = cn.get("depth_background", wf["28"]["inputs"]["bg_threshold"])
    if "23" in wf:
        wf["23"]["inputs"]["strength"]      = cn.get("depth_strength", wf["23"]["inputs"]["strength"])
        wf["23"]["inputs"]["start_percent"] = cn.get("depth_start_percent", wf["23"]["inputs"]["start_percent"])
        wf["23"]["inputs"]["end_percent"]   = cn.get("depth_end_percent", wf["23"]["inputs"]["end_percent"])

def apply_controlnet_params_image_cn(wf, cn):
    if "17" in wf:
        for k in ("detect_hand","detect_body","detect_face"):
            wf["17"]["inputs"][k] = cn.get(k, wf["17"]["inputs"].get(k))
    if "18" in wf:
        wf["18"]["inputs"]["strength"]      = cn.get("strength", wf["18"]["inputs"]["strength"])
        wf["18"]["inputs"]["start_percent"] = cn.get("start_percent", wf["18"]["inputs"]["start_percent"])
        wf["18"]["inputs"]["end_percent"]   = cn.get("end_percent", wf["18"]["inputs"]["end_percent"])
    # 深度
    if "28" in wf:
        wf["28"]["inputs"]["a"]            = cn.get("depth_angle", wf["28"]["inputs"]["a"])
        wf["28"]["inputs"]["bg_threshold"] = cn.get("depth_background", wf["28"]["inputs"]["bg_threshold"])
    if "23" in wf:
        wf["23"]["inputs"]["strength"]      = cn.get("depth_strength", wf["23"]["inputs"]["strength"])
        wf["23"]["inputs"]["start_percent"] = cn.get("depth_start_percent", wf["23"]["inputs"]["start_percent"])
        wf["23"]["inputs"]["end_percent"]   = cn.get("depth_end_percent", wf["23"]["inputs"]["end_percent"])


# ----------------------------
# 文生模式 Endpoint
# ----------------------------
@app.route("/pose_control_text", methods=["POST"])
def pose_control_text():
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error":"缺少 prompt"}), 400

    # 列印接收的參數
    expected = ["prompt","vae_name","checkpoint_name","cfg_scale","sampler",
                "scheduler","denoise_strength","seed","pose_image",
                "lora_name","strength_model","strength_clip","control_net_params"]
    received = {k: data.get(k) for k in expected if k in data}
    print("=== Received Params (Text Mode) ===")
    for k,v in received.items():
        print(f"{k}: {v}")
    print("===================================")

    # 取基本參數
    prompt_text = data["prompt"].strip()
    cfg_scale   = int(data.get("cfg_scale",7))
    sampler     = data.get("sampler","euler")
    scheduler   = data.get("scheduler","normal")
    seed        = int(data.get("seed",0))
    pose_b64    = data.get("pose_image","").strip()
    cn_params   = data.get("control_net_params",{})

    # 選 Workflow
    wf_str = WORKFLOW_TEXT_CN if pose_b64 else WORKFLOW_TEXT_BASE
    wf = json.loads(wf_str)

    # 動態切換 ckpt & vae
    if data.get("checkpoint_name"):
        wf["1"]["inputs"]["ckpt_name"] = data["checkpoint_name"]
    if data.get("vae_name"):
        wf["9"]["inputs"]["vae_name"] = data["vae_name"]

    # 動態套用 LoRA
    lora = data.get("lora_name")
    if lora:
        sm = float(data.get("strength_model",1.0))
        sc = float(data.get("strength_clip",1.0))
        for nid,node in wf.items():
            if node.get("class_type")=="LoraLoader":
                node["inputs"]["lora_name"]      = lora
                node["inputs"]["strength_model"] = sm
                node["inputs"]["strength_clip"]  = sc

    # 填 prompt & sampler 參數
    wf["2"]["inputs"]["text"]         = prompt_text
    wf["4"]["inputs"]["cfg"]          = cfg_scale
    wf["4"]["inputs"]["sampler_name"] = sampler
    wf["4"]["inputs"]["scheduler"]    = scheduler
    wf["4"]["inputs"]["seed"]         = seed

    # 注入姿勢圖
    if pose_b64:
        _,enc = pose_b64.split(",",1)
        fn = f"pose_{uuid.uuid4().hex}.png"
        path = os.path.join(temp_dir,fn)
        with open(path,"wb") as f:
            f.write(base64.b64decode(enc))
        wf["48"]["inputs"]["image_path"] = path
        wf["50"]["inputs"]["image_path"] = path
        apply_controlnet_params_text_cn(wf,cn_params)

    # 送出
    resp = queue_prompt(wf)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error":"ComfyUI 無回應"}),500
    pid,cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid,cid)

    new_fn = move_output_files(pid, target_dir_text)
    if not new_fn:
        return jsonify({"error":"搬移檔案失敗"}),500
    url = f"{EXTERNAL_API_URL}/get_image/{new_fn}?t={int(time.time())}"
    return jsonify({"image_url":url})

# ----------------------------
# 圖生模式 Endpoint
# ----------------------------
@app.route("/pose_control_image", methods=["POST"])
def pose_control_image():
    data = request.get_json()
    if not data or "prompt" not in data or "image" not in data:
        return jsonify({"error":"缺少 prompt 或 image"}),400

    # 列印接收的參數
    expected = ["prompt","vae_name","checkpoint_name","cfg_scale","sampler",
                "scheduler","denoise_strength","seed","image","pose_image",
                "lora_name","strength_model","strength_clip","control_net_params"]
    received = {k: data.get(k) for k in expected if k in data}
    print("=== Received Params (Image Mode) ===")
    for k,v in received.items():
        print(f"{k}: {v}")
    print("====================================")

    # 基本
    prompt_text = data["prompt"].strip()
    main_b64    = data["image"].strip()
    cfg_scale   = int(data.get("cfg_scale",7))
    sampler     = data.get("sampler","euler")
    scheduler   = data.get("scheduler","normal")
    seed        = int(data.get("seed",0))
    pose_b64    = data.get("pose_image","").strip()
    cn_params   = data.get("control_net_params",{})

    wf_str = WORKFLOW_IMAGE_CN if pose_b64 else WORKFLOW_IMAGE_BASE
    wf = json.loads(wf_str)

    # 切換 ckpt & vae
    if data.get("checkpoint_name"):
        wf["1"]["inputs"]["ckpt_name"] = data["checkpoint_name"]
    if data.get("vae_name"):
        wf["9"]["inputs"]["vae_name"] = data["vae_name"]

    # LoRA
    lora = data.get("lora_name")
    if lora:
        sm = float(data.get("strength_model",1.0))
        sc = float(data.get("strength_clip",1.0))
        for nid,node in wf.items():
            if node.get("class_type")=="LoraLoader":
                node["inputs"]["lora_name"]      = lora
                node["inputs"]["strength_model"] = sm
                node["inputs"]["strength_clip"]  = sc

    # 填 prompt & sampler
    wf["2"]["inputs"]["text"]         = prompt_text
    wf["4"]["inputs"]["cfg"]          = cfg_scale
    wf["4"]["inputs"]["sampler_name"] = sampler
    wf["4"]["inputs"]["scheduler"]    = scheduler
    wf["4"]["inputs"]["seed"]         = seed

    # 解碼主圖
    _,enc = main_b64.split(",",1)
    fn = f"main_{uuid.uuid4().hex}.png"
    path = os.path.join(temp_dir,fn)
    with open(path,"wb") as f:
        f.write(base64.b64decode(enc))
    wf["47"]["inputs"]["image_path"] = path

    # 注入姿勢
    if pose_b64:
        _,enc2 = pose_b64.split(",",1)
        fn2 = f"pose_{uuid.uuid4().hex}.png"
        path2 = os.path.join(temp_dir,fn2)
        with open(path2,"wb") as f:
            f.write(base64.b64decode(enc2))
        wf["49"]["inputs"]["image_path"] = path2
        wf["50"]["inputs"]["image_path"] = path2
        apply_controlnet_params_image_cn(wf,cn_params)

    resp = queue_prompt(wf)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error":"ComfyUI 無回應"}),500
    pid,cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid,cid)

    new_fn = move_output_files(pid, target_dir_image)
    if not new_fn:
        return jsonify({"error":"搬移檔案失敗"}),500
    url = f"{EXTERNAL_API_URL}/get_image/{new_fn}?t={int(time.time())}"
    return jsonify({"image_url":url})

# ----------------------------
# 取圖 Proxy
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
        return jsonify({"error":"檔案不存在"}),404
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"]        = "no-cache"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5015, debug=False)
