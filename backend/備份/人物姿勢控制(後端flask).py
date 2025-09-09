# image_generation_flask.py
import os
import json
import shutil
import time
import uuid
import base64
import urllib.request
import urllib.parse
import websocket  # pip install websocket-client
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# -----------------------------------
# ComfyUI 位置 & 資料夾設定
# -----------------------------------
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器地址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"

# 生成結果存放（文生與圖生分開）
target_dir_text = r"D:\大模型文生圖姿勢控制"
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
"""

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
"""

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
"""

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
"""

# -----------------------------------
# 小工具：queue_prompt, wait_for_completion, get_history, find_latest_png, get_final_image_filename, move_output_files
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
    print("🕐 等待 ComfyUI 任務完成...")
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message.get("type") == "executing":
                    data = message.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
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
        print(f"📜 Debug: history API 回應 = {json.dumps(all_data, indent=2, ensure_ascii=False)}")
        return all_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_png(comfyui_output_dir)
    outputs = history.get("outputs", {})
    node_7 = outputs.get("7", {})
    if "images" in node_7:
        for info in node_7["images"]:
            fn = info.get("filename")
            if fn and fn.lower().endswith(".png"):
                print(f"🎞 從 API 取得圖片檔名: {fn}")
                return fn
    print("⚠️ /history API 未提供圖片檔名，改用檔案搜尋。")
    return find_latest_png(comfyui_output_dir)

def move_output_files(prompt_id, target_folder):
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        return None
    source_path = os.path.join(comfyui_output_dir, image_filename)
    if not os.path.exists(source_path):
        return None
    dest_path = os.path.join(target_folder, image_filename)
    try:
        shutil.move(source_path, dest_path)
        print(f"✅ 搬移 {source_path} -> {dest_path}")
        return image_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None

# -----------------------------------
# 小工具：套用 ControlNet 參數到 workflow（分文生與圖生）
# -----------------------------------
def apply_controlnet_params_to_workflow_text_cn(workflow, cn_params):
    # 修改 OpenPose 節點（假設 node #17）
    if "17" in workflow and "inputs" in workflow["17"]:
        workflow["17"]["inputs"]["detect_hand"] = cn_params.get("detect_hand", "enable")
        workflow["17"]["inputs"]["detect_body"] = cn_params.get("detect_body", "enable")
        workflow["17"]["inputs"]["detect_face"] = cn_params.get("detect_face", "disable")
    # 修改 ControlNetApplyAdvanced 節點（假設 node #18 與 node #23）
    strength = float(cn_params.get("strength", 1.0))
    s_start = float(cn_params.get("start_percent", 0.0))
    s_end = float(cn_params.get("end_percent", 1.0))
    if "18" in workflow and "inputs" in workflow["18"]:
        workflow["18"]["inputs"]["strength"] = strength
        workflow["18"]["inputs"]["start_percent"] = s_start
        workflow["18"]["inputs"]["end_percent"] = s_end
    if "23" in workflow and "inputs" in workflow["23"]:
        workflow["23"]["inputs"]["strength"] = strength
        workflow["23"]["inputs"]["start_percent"] = s_start
        workflow["23"]["inputs"]["end_percent"] = s_end

def apply_controlnet_params_to_workflow_image_cn(workflow, cn_params):
    # 修改 OpenPose 節點（假設 node #17）
    if "17" in workflow and "inputs" in workflow["17"]:
        workflow["17"]["inputs"]["detect_hand"] = cn_params.get("detect_hand", "enable")
        workflow["17"]["inputs"]["detect_body"] = cn_params.get("detect_body", "enable")
        workflow["17"]["inputs"]["detect_face"] = cn_params.get("detect_face", "disable")
    # 修改 ControlNetApplyAdvanced 節點（假設 node #18 與 node #23）
    strength = float(cn_params.get("strength", 1.0))
    s_start = float(cn_params.get("start_percent", 0.0))
    s_end = float(cn_params.get("end_percent", 1.0))
    if "18" in workflow and "inputs" in workflow["18"]:
        workflow["18"]["inputs"]["strength"] = strength
        workflow["18"]["inputs"]["start_percent"] = s_start
        workflow["18"]["inputs"]["end_percent"] = s_end
    if "23" in workflow and "inputs" in workflow["23"]:
        workflow["23"]["inputs"]["strength"] = strength
        workflow["23"]["inputs"]["start_percent"] = s_start
        workflow["23"]["inputs"]["end_percent"] = s_end

# -----------------------------------
# Flask Routes
# -----------------------------------
@app.route("/pose_control_text", methods=["POST"])
def pose_control_text():
    """
    文生模式:
      - 若有上傳姿勢圖 => 使用 WORKFLOW_TEXT_CN 並套用 control_net_params
      - 否則使用 WORKFLOW_TEXT_BASE
    """
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "缺少 prompt 參數"}), 400

    prompt_text = data["prompt"].strip()
    cfg_scale = int(data.get("cfg_scale", 7))
    sampler = data.get("sampler", "dpmpp_2m_sde")
    scheduler = data.get("scheduler", "karras")
    seed = int(data.get("seed", 87))
    pose_image_b64 = data.get("pose_image", "").strip()
    cn_params = data.get("control_net_params", {})

    # 選擇 workflow
    if pose_image_b64:
        print("🔸 文生: 使用含 ControlNet workflow")
        workflow_str = WORKFLOW_TEXT_CN
    else:
        print("🔸 文生: 使用無 ControlNet workflow")
        workflow_str = WORKFLOW_TEXT_BASE

    try:
        workflow = json.loads(workflow_str)
    except Exception as e:
        return jsonify({"error": f"Workflow JSON 解析失敗: {e}"}), 500

    # 修改基本參數
    if "2" in workflow and "inputs" in workflow["2"]:
        workflow["2"]["inputs"]["text"] = prompt_text
    if "4" in workflow and "inputs" in workflow["4"]:
        workflow["4"]["inputs"]["cfg"] = cfg_scale
        workflow["4"]["inputs"]["sampler_name"] = sampler
        workflow["4"]["inputs"]["scheduler"] = scheduler
        workflow["4"]["inputs"]["seed"] = seed

    # 若有上傳姿勢圖，則解碼並覆蓋 workflow 的相關節點 (更新 node 48 與 node 50)
    if pose_image_b64:
        try:
            _, encoded = pose_image_b64.split(",", 1)
            pose_filename = f"pose_{uuid.uuid4().hex}.png"
            pose_path = os.path.join(temp_dir, pose_filename)
            with open(pose_path, "wb") as f:
                f.write(base64.b64decode(encoded))
            print(f"✅ 文生: 姿勢圖存檔 {pose_path}")
            if "48" in workflow and "inputs" in workflow["48"]:
                workflow["48"]["inputs"]["image_path"] = pose_path
            if "50" in workflow and "inputs" in workflow["50"]:
                workflow["50"]["inputs"]["image_path"] = pose_path
        except Exception as e:
            print(f"❌ 文生: 姿勢圖解碼失敗: {e}")
        # 套用 ControlNet 參數
        apply_controlnet_params_to_workflow_text_cn(workflow, cn_params)

    print("🚀 文生: 發送 workflow 至 ComfyUI...")
    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無回應"}), 500
    pid = resp["prompt_id"]
    cid = resp["client_id"]
    wait_for_completion(pid, cid)

    # 搬移生成的圖到文生目標資料夾
    fn = move_output_files(pid, target_dir_text)
    if not fn:
        return jsonify({"error": "搬移檔案失敗"}), 500

    image_url = f"{EXTERNAL_API_URL}/get_image/{fn}?t={int(time.time())}"
    print("最終回傳(文生):", image_url)
    return jsonify({"image_url": image_url})


@app.route("/pose_control_image", methods=["POST"])
def pose_control_image():
    """
    圖生模式:
      - 必須有主圖 (image) 的 base64
      - 若有上傳姿勢圖 => 使用 WORKFLOW_IMAGE_CN 並套用 control_net_params
      - 否則使用 WORKFLOW_IMAGE_BASE
    """
    data = request.get_json()
    if not data or "prompt" not in data or "image" not in data:
        return jsonify({"error": "缺少 prompt 或 image 參數"}), 400

    prompt_text = data["prompt"].strip()
    main_b64 = data["image"].strip()

    cfg_scale = int(data.get("cfg_scale", 7))
    sampler = data.get("sampler", "dpmpp_2m_sde")
    scheduler = data.get("scheduler", "karras")
    seed = int(data.get("seed", 87))
    pose_b64 = data.get("pose_image", "").strip()
    cn_params = data.get("control_net_params", {})

     # 選擇 workflow
    if pose_b64:
        print("🔸 圖生: 使用含 ControlNet workflow")
        workflow_str = WORKFLOW_IMAGE_CN
    else:
        print("🔸 圖生: 使用無 ControlNet workflow")
        workflow_str = WORKFLOW_IMAGE_BASE

    try:
        workflow = json.loads(workflow_str)
    except Exception as e:
        return jsonify({"error": f"Workflow JSON 解析失敗: {e}"}), 500

    # 修改基本參數
    if "2" in workflow and "inputs" in workflow["2"]:
        workflow["2"]["inputs"]["text"] = prompt_text
    if "4" in workflow and "inputs" in workflow["4"]:
        workflow["4"]["inputs"]["cfg"] = cfg_scale
        workflow["4"]["inputs"]["sampler_name"] = sampler
        workflow["4"]["inputs"]["scheduler"] = scheduler
        workflow["4"]["inputs"]["seed"] = seed

    # 主圖處理 => 更新 node 47
    try:
        _, main_encoded = main_b64.split(",", 1)
        main_filename = f"main_{uuid.uuid4().hex}.png"
        main_path = os.path.join(temp_dir, main_filename)
        with open(main_path, "wb") as f:
            f.write(base64.b64decode(main_encoded))
        print(f"✅ 圖生: 主圖存檔 {main_path}")
        if "47" in workflow and "inputs" in workflow["47"]:
            workflow["47"]["inputs"]["image_path"] = main_path
    except Exception as e:
        return jsonify({"error": f"主圖解碼失敗: {e}"}), 400

    # 若有上傳姿勢圖 => 更新 node 49 與 node 50
    if pose_b64:
        try:
            _, pose_encoded = pose_b64.split(",", 1)
            pose_filename = f"pose_{uuid.uuid4().hex}.png"
            pose_path = os.path.join(temp_dir, pose_filename)
            with open(pose_path, "wb") as f:
                f.write(base64.b64decode(pose_encoded))
            print(f"✅ 圖生: 姿勢圖存檔 {pose_path}")
            if "49" in workflow and "inputs" in workflow["49"]:
                workflow["49"]["inputs"]["image_path"] = pose_path
            if "50" in workflow and "inputs" in workflow["50"]:
                workflow["50"]["inputs"]["image_path"] = pose_path
        except Exception as e:
            print(f"❌ 圖生: 姿勢圖解碼失敗: {e}")
        # 套用 ControlNet 參數
        apply_controlnet_params_to_workflow_image_cn(workflow, cn_params)

    print("🚀 圖生: 發送 workflow 至 ComfyUI...")
    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI 無回應"}), 500
    pid = resp["prompt_id"]
    cid = resp["client_id"]
    wait_for_completion(pid, cid)

    # 搬移生成的圖到圖生目標資料夾
    fn = move_output_files(pid, target_dir_image)
    if not fn:
        return jsonify({"error": "搬移檔案失敗"}), 500

    image_url = f"{EXTERNAL_API_URL}/get_image/{fn}?t={int(time.time())}"
    print("最終回傳(圖生):", image_url)
    return jsonify({"image_url": image_url})


@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    t_path = os.path.join(target_dir_text, filename)
    i_path = os.path.join(target_dir_image, filename)
    if os.path.exists(t_path):
        response = make_response(send_from_directory(target_dir_text, filename))
    elif os.path.exists(i_path):
        response = make_response(send_from_directory(target_dir_image, filename))
    else:
        return jsonify({"error": "檔案不存在"}), 404

    # 加入 Cache-Control 標頭避免瀏覽器/代理快取
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=False)
