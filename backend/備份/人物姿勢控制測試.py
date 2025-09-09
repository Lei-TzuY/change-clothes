#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import uuid
import time
import base64
import urllib.request
import websocket  # pip install websocket-client
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------------------------
# ComfyUI 伺服器 & 資料夾設定
# ----------------------------------
COMFYUI_SERVER     = "127.0.0.1:8188"
COMFYUI_OUTPUT_DIR = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
TEMP_DIR           = r"D:\comfyui\temp_images"
TARGET_TEXT_DIR    = r"D:\大模型文生姿勢控制圖"
TARGET_IMAGE_DIR   = r"D:\大模型圖生姿勢控制圖"
EXTERNAL_API_URL   = "https://pose.picturesmagician.com"

for d in (TEMP_DIR, TARGET_TEXT_DIR, TARGET_IMAGE_DIR):
    os.makedirs(d, exist_ok=True)

# ----------------------------------
# 工作流程 JSON (文生無 ControlNet)
# ----------------------------------
WORKFLOW_TEXT_BASE = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands.", "clip": ["1", 1]} },
  "47": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width": 512, "height": 512, "batch_size": 1}
  },
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
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["4", 0], "vae": ["9", 0]}
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "kl-f8-anime2.safetensors"}
  }
}
""".strip()

# ----------------------------------
# 工作流程 JSON (文生有 ControlNet—OpenPose+Depth)
# ----------------------------------
WORKFLOW_TEXT_CN = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands.", "clip": ["1", 1]} },
  "47": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width":512,"height":512,"batch_size":1}
  },
  "48": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": ""}
  },
  "50": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": ""}
  },
  "17": {
    "class_type": "OpenposePreprocessor",
    "inputs": {
      "detect_hand":"enable",
      "detect_body":"enable",
      "detect_face":"disable",
      "resolution":512,
      "scale_stick_for_xinsr_cn":"disable",
      "image":["48",0]
    }
  },
  "18": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength":1.2,
      "start_percent":0,
      "end_percent":1,
      "positive":["2",0],
      "negative":["3",0],
      "control_net":["19",0],
      "image":["17",0],
      "vae":["9",0]
    }
  },
  "19": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name":"control_sd15_openpose.pth"}
  },
  "28": {
    "class_type": "MiDaS-DepthMapPreprocessor",
    "inputs": {
      "a":0,
      "bg_threshold":0.1,
      "resolution":512,
      "image":["50",0]
    }
  },
  "23": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength":1.0,
      "start_percent":0,
      "end_percent":1,
      "positive":["18",0],
      "negative":["18",1],
      "control_net":["24",0],
      "image":["28",0],
      "vae":["9",0]
    }
  },
  "24": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name":"control_sd15_depth.pth"}
  },
  "4": {
    "class_type": "KSampler",
    "inputs": {
      "seed":87,
      "steps":20,
      "cfg":7,
      "sampler_name":"dpmpp_2m_sde",
      "scheduler":"karras",
      "denoise":1,
      "model":["1",0],
      "positive":["23",0],
      "negative":["23",1],
      "latent_image":["47",0]
    }
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples":["4",0],"vae":["9",0]}
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix":"ComfyUI","images":["8",0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name":"kl-f8-anime2.safetensors"}
  }
}
""".strip()

# ----------------------------------
# 工作流程 JSON (圖生無 ControlNet)
# ----------------------------------
WORKFLOW_IMAGE_BASE = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands.", "clip": ["1", 1]} },
  "47": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width":512,"height":512,"batch_size":1}
  },
  "48": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": ""}
  },
  "4": {
    "class_type": "KSampler",
    "inputs": {
      "seed":87,
      "steps":20,
      "cfg":7,
      "sampler_name":"dpmpp_2m_sde",
      "scheduler":"karras",
      "denoise":1,
      "model":["1",0],
      "positive":["2",0],
      "negative":["3",0],
      "latent_image":["47",0]
    }
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples":["4",0],"vae":["9",0]}
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix":"ComfyUI","images":["8",0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name":"kl-f8-anime2.safetensors"}
  }
}
""".strip()

# ----------------------------------
# 工作流程 JSON (圖生有 ControlNet)
# ----------------------------------
WORKFLOW_IMAGE_CN = r"""
{
  "1": { "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "meinamix_v12Final.safetensors"} },
  "2": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "example prompt", "clip": ["1", 1]} },
  "3": { "class_type": "CLIPTextEncode",
         "inputs": {"text": "bad hands.", "clip": ["1", 1]} },
  "47": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": ""}
  },
  "48": {
    "class_type": "ZwngLoadImagePathOrURL",
    "inputs": {"image_path": ""}
  },
  "17": {
    "class_type": "OpenposePreprocessor",
    "inputs": {
      "detect_hand":"enable",
      "detect_body":"enable",
      "detect_face":"disable",
      "resolution":512,
      "scale_stick_for_xinsr_cn":"disable",
      "image":["48",0]
    }
  },
  "18": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength":1.2,
      "start_percent":0,
      "end_percent":1,
      "positive":["2",0],
      "negative":["3",0],
      "control_net":["19",0],
      "image":["17",0],
      "vae":["9",0]
    }
  },
  "19": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name":"control_sd15_openpose.pth"} 
  },
  "28": {
    "class_type": "MiDaS-DepthMapPreprocessor",
    "inputs": {
      "a":0,
      "bg_threshold":0.1,
      "resolution":512,
      "image":["50",0]
    }
  },
  "23": {
    "class_type": "ControlNetApplyAdvanced",
    "inputs": {
      "strength":1.0,
      "start_percent":0,
      "end_percent":1,
      "positive":["18",0],
      "negative":["18",1],
      "control_net":["24",0],
      "image":["28",0],
      "vae":["9",0]
    }
  },
  "24": {
    "class_type": "ControlNetLoader",
    "inputs": {"control_net_name":"control_sd15_depth.pth"} 
  },
  "4": { "class_type": "KSampler",
    "inputs": {
      "seed":87,
      "steps":20,
      "cfg":7,
      "sampler_name":"dpmpp_2m_sde",
      "scheduler":"karras",
      "denoise":1,
      "model":["1",0],
      "positive":["23",0],
      "negative":["23",1],
      "latent_image":["47",0]
    }
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples":["4",0],"vae":["9",0]}
  },
  "7": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix":"ComfyUI","images":["8",0]}
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name":"kl-f8-anime2.safetensors"}
  }
}
""".strip()

# ----------------------------------
# 輔助函式
# ----------------------------------
def queue_prompt(workflow_dict):
    client_id = str(uuid.uuid4())
    payload   = {"prompt": workflow_dict, "client_id": client_id}
    data      = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{COMFYUI_SERVER}/prompt",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        result["client_id"] = client_id
        return result

def wait_for_completion(prompt_id, client_id):
    ws = websocket.create_connection(f"ws://{COMFYUI_SERVER}/ws?clientId={client_id}", timeout=60)
    while True:
        msg = ws.recv()
        if isinstance(msg, str):
            m = json.loads(msg)
            if m.get("type") == "executing":
                data = m.get("data", {})
                if data.get("prompt_id") == prompt_id and data.get("node") is None:
                    break
    ws.close()

def find_latest_png(directory):
    pngs = [f for f in os.listdir(directory) if f.lower().endswith(".png")]
    return max(pngs, key=lambda fn: os.path.getctime(os.path.join(directory, fn))) if pngs else None

def get_final_image_filename(prompt_id):
    return find_latest_png(COMFYUI_OUTPUT_DIR)

def move_output_files(prompt_id, target_folder):
    fn = get_final_image_filename(prompt_id)
    if not fn:
        return None
    src = os.path.join(COMFYUI_OUTPUT_DIR, fn)
    new_fn = f"{prompt_id.replace('-', '')[:8]}_{fn}"
    dst = os.path.join(target_folder, new_fn)
    os.replace(src, dst)
    return new_fn

def apply_controlnet_params_to_workflow_text_cn(workflow, cn):
    if "17" in workflow:
        inp = workflow["17"]["inputs"]
        pp = cn.get("pose_preprocessor", {})
        inp["detect_hand"] = pp.get("detect_hand", "enable")
        inp["detect_body"] = pp.get("detect_body", "enable")
        inp["detect_face"] = pp.get("detect_face", "disable")
    # OpenPose & Depth strength
    op = cn.get("openpose", {})
    for idx in ("18", "23"):
        if idx in workflow:
            workflow[idx]["inputs"]["strength"]      = float(op.get("strength", 1.0))
            workflow[idx]["inputs"]["start_percent"] = float(op.get("start_percent", 0.0))
            workflow[idx]["inputs"]["end_percent"]   = float(op.get("end_percent", 1.0))

def apply_controlnet_params_to_workflow_image_cn(workflow, cn):
    apply_controlnet_params_to_workflow_text_cn(workflow, cn)

# ----------------------------------
# 文生模式：Pose Control
# ----------------------------------
@app.route("/pose_control_text", methods=["POST"])
def pose_control_text():
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "缺少 prompt"}), 400

    expected = [
        "prompt", "vae_name", "checkpoint_name",
        "cfg_scale", "sampler", "scheduler",
        "denoise_strength", "seed",
        "pose_image", "control_net_params"
    ]
    received = {k: data.get(k) for k in expected if k in data}
    print("=== Received Params (Text Mode) ===")
    for k, v in received.items():
        print(f"{k}: {v}")
    print("===================================")

    workflow_str = WORKFLOW_TEXT_CN if data.get("pose_image") else WORKFLOW_TEXT_BASE
    workflow     = json.loads(workflow_str)

    # 填入參數
    workflow["2"]["inputs"]["text"]         = data["prompt"].strip()
    workflow["4"]["inputs"]["cfg"]          = int(data.get("cfg_scale", 7))
    workflow["4"]["inputs"]["sampler_name"] = data.get("sampler", "euler")
    workflow["4"]["inputs"]["scheduler"]    = data.get("scheduler", "normal")
    workflow["4"]["inputs"]["seed"]         = int(data.get("seed", 0))
    workflow["4"]["inputs"]["denoise"]      = float(data.get("denoise_strength", 1.0))

    # 解碼 & 存姿勢圖
    if data.get("pose_image"):
        _, b64 = data["pose_image"].split(",", 1)
        fn = f"pose_{uuid.uuid4().hex}.png"
        fp = os.path.join(TEMP_DIR, fn)
        with open(fp, "wb") as f:
            f.write(base64.b64decode(b64))
        workflow["48"]["inputs"]["image_path"] = fp
        workflow["50"]["inputs"]["image_path"] = fp
        apply_controlnet_params_to_workflow_text_cn(workflow, data.get("control_net_params", {}))

    # 套用 checkpoint
    if data.get("checkpoint_name"):
        workflow["1"]["inputs"]["ckpt_name"] = data["checkpoint_name"]
    # 套用 VAE（僅當節點 9 存在時）
    if data.get("vae_name") and "9" in workflow:
        workflow["9"]["inputs"]["vae_name"] = data["vae_name"]

    print("🚀 Sending Text Mode prompt to ComfyUI…")
    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無回應"}), 500

    pid, cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid, cid)
    fn = move_output_files(pid, TARGET_TEXT_DIR)
    if not fn:
        return jsonify({"error": "搬檔失敗"}), 500

    url = f"{EXTERNAL_API_URL}/output/{fn}?t={int(time.time())}"
    return jsonify({"image_url": url, "receivedParams": received})

# ----------------------------------
# 圖生模式：Pose Control
# ----------------------------------
@app.route("/pose_control_image", methods=["POST"])
def pose_control_image():
    data = request.get_json()
    if not data or "prompt" not in data or "image" not in data:
        return jsonify({"error": "缺少 prompt 或 image"}), 400

    expected = [
        "prompt", "vae_name", "checkpoint_name",
        "cfg_scale", "sampler", "scheduler",
        "denoise_strength", "seed",
        "image", "pose_image", "control_net_params"
    ]
    received = {k: data.get(k) for k in expected if k in data}
    print("=== Received Params (Image Mode) ===")
    for k, v in received.items():
        print(f"{k}: {v}")
    print("====================================")

    workflow_str = WORKFLOW_IMAGE_CN if data.get("pose_image") else WORKFLOW_IMAGE_BASE
    workflow     = json.loads(workflow_str)

    # 填入參數
    workflow["2"]["inputs"]["text"]         = data["prompt"].strip()
    workflow["4"]["inputs"]["cfg"]          = int(data.get("cfg_scale", 7))
    workflow["4"]["inputs"]["sampler_name"] = data.get("sampler", "euler")
    workflow["4"]["inputs"]["scheduler"]    = data.get("scheduler", "normal")
    workflow["4"]["inputs"]["seed"]         = int(data.get("seed", 0))
    workflow["4"]["inputs"]["denoise"]      = float(data.get("denoise_strength", 1.0))

    # 解碼 & 存主圖
    _, main_b64 = data["image"].split(",", 1)
    fn_main = f"main_{uuid.uuid4().hex}.png"
    fp_main = os.path.join(TEMP_DIR, fn_main)
    with open(fp_main, "wb") as f:
        f.write(base64.b64decode(main_b64))
    workflow["47"]["inputs"]["image_path"] = fp_main

    # 解碼 & 存姿勢圖
    if data.get("pose_image"):
        _, pose_b64 = data["pose_image"].split(",", 1)
        fn_pose = f"pose_{uuid.uuid4().hex}.png"
        fp_pose = os.path.join(TEMP_DIR, fn_pose)
        with open(fp_pose, "wb") as f:
            f.write(base64.b64decode(pose_b64))
        workflow["48"]["inputs"]["image_path"] = fp_pose
        workflow["50"]["inputs"]["image_path"] = fp_pose
        apply_controlnet_params_to_workflow_image_cn(workflow, data.get("control_net_params", {}))

    # 套用 checkpoint
    if data.get("checkpoint_name"):
        workflow["1"]["inputs"]["ckpt_name"] = data["checkpoint_name"]
    # 套用 VAE（僅當節點 9 存在時）
    if data.get("vae_name") and "9" in workflow:
        workflow["9"]["inputs"]["vae_name"] = data["vae_name"]

    print("🚀 Sending Image Mode prompt to ComfyUI…")
    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無回應"}), 500

    pid, cid = resp["prompt_id"], resp["client_id"]
    wait_for_completion(pid, cid)
    fn = move_output_files(pid, TARGET_IMAGE_DIR)
    if not fn:
        return jsonify({"error": "搬檔失敗"}), 500

    url = f"{EXTERNAL_API_URL}/output/{fn}?t={int(time.time())}"
    return jsonify({"image_url": url, "receivedParams": received})

# ----------------------------------
# 啟動服務
# ----------------------------------
if __name__ == "__main__":
    # 開發時使用 Flask，生產請改用 Gunicorn / uWSGI
    app.run(host="0.0.0.0", port=5005, debug=False)
