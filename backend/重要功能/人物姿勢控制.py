# image_generation_flask.py
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
CORS(app)

# -----------------------------------
# ComfyUI 位置 & 資料夾設定 (保持原樣)
# -----------------------------------
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器地址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"

# 生成結果存放（文生與圖生分開）
target_dir_text  = r"D:\大模型文生圖姿勢控制"
target_dir_image = r"D:\大模型圖生圖姿勢控制"
os.makedirs(target_dir_text, exist_ok=True)
os.makedirs(target_dir_image, exist_ok=True)

# 暫存上傳檔案（主圖 / 姿勢圖）
temp_dir = r"D:\大模型姿勢控制\temp_input"
os.makedirs(temp_dir, exist_ok=True)

# 外部對應的域名（組合給前端）
EXTERNAL_API_URL = "https://pose.picturesmagician.com"

# -----------------------------------
# 工作流程 JSON（文生模式）
# 分為：無 ControlNet (BASE) 與 有 ControlNet (CN)
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
  "47": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width": 512, "height": 512, "batch_size": 1}
  },
  "48": {
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
# 工作流程 JSON（圖生模式）
# 分為：無 ControlNet (BASE) 與 有 ControlNet (CN)
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
# 小工具：queue_prompt, wait_for_completion, get_history, find_latest_png,
#           get_final_image_filename, move_output_files,
#           apply_controlnet_params_to_workflow_text_cn,
#           apply_controlnet_params_to_workflow_image_cn
# -----------------------------------
def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                msg = json.loads(out)
                if msg.get("type") == "executing":
                    data = msg.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 錯誤: {e}")

def find_latest_png(directory):
    png_list = [f for f in os.listdir(directory) if f.lower().endswith(".png")]
    if not png_list:
        return None
    return max(png_list, key=lambda x: os.path.getctime(os.path.join(directory, x)))

def get_history(prompt_id):
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            all_data = json.loads(resp.read())
        return all_data.get(prompt_id, {})
    except:
        return {}

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    if history and "outputs" in history and "7" in history["outputs"]:
        for info in history["outputs"]["7"]["images"]:
            fn = info.get("filename")
            if fn and fn.lower().endswith(".png"):
                return fn
    return find_latest_png(comfyui_output_dir)

def move_output_files(prompt_id, target_folder):
    fn = get_final_image_filename(prompt_id)
    if not fn:
        return None
    src = os.path.join(comfyui_output_dir, fn)
    dst = os.path.join(target_folder, fn)
    try:
        shutil.move(src, dst)
        return fn
    except:
        return None

def apply_controlnet_params_to_workflow_text_cn(workflow, cn_params):
    # 保持原樣
    if "17" in workflow and "inputs" in workflow["17"]:
        workflow["17"]["inputs"]["detect_hand"] = cn_params.get("detect_hand", "enable")
        workflow["17"]["inputs"]["detect_body"] = cn_params.get("detect_body", "enable")
        workflow["17"]["inputs"]["detect_face"] = cn_params.get("detect_face", "disable")
    strength = float(cn_params.get("strength", 1.0))
    s_start = float(cn_params.get("start_percent", 0.0))
    s_end = float(cn_params.get("end_percent", 1.0))
    if "18" in workflow:
        for node in ["18", "23"]:
            if node in workflow and "inputs" in workflow[node]:
                workflow[node]["inputs"]["strength"] = strength
                workflow[node]["inputs"]["start_percent"] = s_start
                workflow[node]["inputs"]["end_percent"] = s_end

def apply_controlnet_params_to_workflow_image_cn(workflow, cn_params):
    # 保持原樣
    if "17" in workflow and "inputs" in workflow["17"]:
        workflow["17"]["inputs"]["detect_hand"] = cn_params.get("detect_hand", "enable")
        workflow["17"]["inputs"]["detect_body"] = cn_params.get("detect_body", "enable")
        workflow["17"]["inputs"]["detect_face"] = cn_params.get("detect_face", "disable")
    strength = float(cn_params.get("strength", 1.0))
    s_start = float(cn_params.get("start_percent", 0.0))
    s_end = float(cn_params.get("end_percent", 1.0))
    if "18" in workflow:
        for node in ["18", "23"]:
            if node in workflow and "inputs" in workflow[node]:
                workflow[node]["inputs"]["strength"] = strength
                workflow[node]["inputs"]["start_percent"] = s_start
                workflow[node]["inputs"]["end_percent"] = s_end

# -----------------------------------
# 文生模式 Endpoint（已微調）
# -----------------------------------
@app.route("/pose_control_text", methods=["POST"])
def pose_control_text():
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "缺少 prompt 參數"}), 400

    # 列出接收到的參數
    expected_keys = [
        "prompt", "vae_name", "checkpoint_name",
        "cfg_scale", "sampler", "scheduler",
        "denoise_strength", "seed",
        "pose_image", "control_net_params"
    ]
    received_params = {k: data.get(k) for k in expected_keys if k in data}
    print("=== Received Params (Text Mode) ===")
    for k, v in received_params.items():
        print(f"{k}: {v}")
    print("===================================")

    # 原有邏輯
    prompt_text    = data["prompt"].strip()
    cfg_scale      = int(data.get("cfg_scale", 7))
    sampler        = data.get("sampler", "dpmpp_2m_sde")
    scheduler      = data.get("scheduler", "karras")
    seed           = int(data.get("seed", 87))
    pose_image_b64 = data.get("pose_image", "").strip()
    cn_params      = data.get("control_net_params", {})

    workflow_str = WORKFLOW_TEXT_CN if pose_image_b64 else WORKFLOW_TEXT_BASE
    workflow     = json.loads(workflow_str)

    workflow["2"]["inputs"]["text"]       = prompt_text
    workflow["4"]["inputs"]["cfg"]        = cfg_scale
    workflow["4"]["inputs"]["sampler_name"] = sampler
    workflow["4"]["inputs"]["scheduler"]    = scheduler
    workflow["4"]["inputs"]["seed"]         = seed

    if pose_image_b64:
        _, enc = pose_image_b64.split(",", 1)
        pose_fn   = f"pose_{uuid.uuid4().hex}.png"
        pose_path = os.path.join(temp_dir, pose_fn)
        with open(pose_path, "wb") as f:
            f.write(base64.b64decode(enc))
        workflow["48"]["inputs"]["image_path"] = pose_path
        workflow["50"]["inputs"]["image_path"] = pose_path
        apply_controlnet_params_to_workflow_text_cn(workflow, cn_params)

    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無回應"}), 500
    wait_for_completion(resp["prompt_id"], resp["client_id"])

    fn = move_output_files(resp["prompt_id"], target_dir_text)
    if not fn:
        return jsonify({"error": "搬移檔案失敗"}), 500
    image_url = f"{EXTERNAL_API_URL}/get_image/{fn}?t={int(time.time())}"

    return jsonify({
        "image_url":       image_url,
        "receivedParams":  received_params,
        "paramDescriptions": {
            "prompt":             "提示詞文字內容",
            "vae_name":           "VAE 名稱 (可選)",
            "checkpoint_name":    "Checkpoint 名稱 (可選)",
            "cfg_scale":          "CFG 強度 (數值)",
            "sampler":            "採樣器名稱",
            "scheduler":          "調度器名稱",
            "denoise_strength":   "去噪幅度 (0~1)",
            "seed":               "隨機種子數值",
            "pose_image":         "姿勢圖 Base64 (可選)",
            "control_net_params": "ControlNet 參數物件"
        }
    })

# -----------------------------------
# 圖生模式 Endpoint（已微調）
# -----------------------------------
@app.route("/pose_control_image", methods=["POST"])
def pose_control_image():
    data = request.get_json()
    if not data or "prompt" not in data or "image" not in data:
        return jsonify({"error": "缺少 prompt 或 image 參數"}), 400

    # 列出接收到的參數
    expected_keys = [
        "prompt", "vae_name", "checkpoint_name",
        "cfg_scale", "sampler", "scheduler",
        "denoise_strength", "seed",
        "image", "pose_image", "control_net_params"
    ]
    received_params = {k: data.get(k) for k in expected_keys if k in data}
    print("=== Received Params (Image Mode) ===")
    for k, v in received_params.items():
        print(f"{k}: {v}")
    print("====================================")

    # 原有邏輯
    prompt_text = data["prompt"].strip()
    main_b64    = data["image"].strip()
    cfg_scale   = int(data.get("cfg_scale", 7))
    sampler     = data.get("sampler", "dpmpp_2m_sde")
    scheduler   = data.get("scheduler", "karras")
    seed        = int(data.get("seed", 87))
    pose_b64    = data.get("pose_image", "").strip()
    cn_params   = data.get("control_net_params", {})

    workflow_str = WORKFLOW_IMAGE_CN if pose_b64 else WORKFLOW_IMAGE_BASE
    workflow     = json.loads(workflow_str)

    workflow["2"]["inputs"]["text"]         = prompt_text
    workflow["4"]["inputs"]["cfg"]          = cfg_scale
    workflow["4"]["inputs"]["sampler_name"] = sampler
    workflow["4"]["inputs"]["scheduler"]    = scheduler
    workflow["4"]["inputs"]["seed"]         = seed

    # 解碼主圖
    _, main_enc = main_b64.split(",", 1)
    main_fn     = f"main_{uuid.uuid4().hex}.png"
    main_path   = os.path.join(temp_dir, main_fn)
    with open(main_path, "wb") as f:
        f.write(base64.b64decode(main_enc))
    workflow["47"]["inputs"]["image_path"] = main_path

    # 解碼姿勢圖並套用 ControlNet
    if pose_b64:
        _, pose_enc = pose_b64.split(",", 1)
        pose_fn     = f"pose_{uuid.uuid4().hex}.png"
        pose_path   = os.path.join(temp_dir, pose_fn)
        with open(pose_path, "wb") as f:
            f.write(base64.b64decode(pose_enc))
        workflow["49"]["inputs"]["image_path"] = pose_path
        workflow["50"]["inputs"]["image_path"] = pose_path
        apply_controlnet_params_to_workflow_image_cn(workflow, cn_params)

    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無回應"}), 500
    wait_for_completion(resp["prompt_id"], resp["client_id"])

    fn = move_output_files(resp["prompt_id"], target_dir_image)
    if not fn:
        return jsonify({"error": "搬移檔案失敗"}), 500
    image_url = f"{EXTERNAL_API_URL}/get_image/{fn}?t={int(time.time())}"

    return jsonify({
        "image_url":       image_url,
        "receivedParams":  received_params,
        "paramDescriptions": {
            "prompt":             "提示詞文字內容",
            "vae_name":           "VAE 名稱 (可選)",
            "checkpoint_name":    "Checkpoint 名稱 (可選)",
            "cfg_scale":          "CFG 強度 (數值)",
            "sampler":            "採樣器名稱",
            "scheduler":          "調度器名稱",
            "denoise_strength":   "去噪幅度 (0~1)",
            "seed":               "隨機種子數值",
            "image":              "主圖 Base64 編碼",
            "pose_image":         "姿勢圖 Base64 (可選)",
            "control_net_params": "ControlNet 參數物件"
        }
    })

# -----------------------------------
# 圖片代理 & 啟動 (保持原樣)
# -----------------------------------
@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    t_path = os.path.join(target_dir_text, filename)
    i_path = os.path.join(target_dir_image, filename)
    if os.path.exists(t_path):
        resp = make_response(send_from_directory(target_dir_text, filename))
    elif os.path.exists(i_path):
        resp = make_response(send_from_directory(target_dir_image, filename))
    else:
        return jsonify({"error": "檔案不存在"}), 404
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"]        = "no-cache"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=False)
