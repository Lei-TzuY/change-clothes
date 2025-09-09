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
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器位址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
temp_input_dir = r"D:\大模型局部重繪\temp_input"
os.makedirs(temp_input_dir, exist_ok=True)

# 依據模式選擇目標資料夾
target_dir_redraw = r"D:\大模型局部重繪"
target_dir_reverse = r"D:\大模型局部重繪反轉"
os.makedirs(target_dir_redraw, exist_ok=True)
os.makedirs(target_dir_reverse, exist_ok=True)

# 新增：存放單純繪畫（純筆刷繪製內容，不含原圖背景）的資料夾
pure_painting_dir = r"D:\大模型局部重繪\pure_painting"
os.makedirs(pure_painting_dir, exist_ok=True)

# 外網對外提供的域名（Cloudflare Tunnel 提供的 HTTPS 網域）
EXTERNAL_URL = "https://inpant.picturesmagician.com"

# =============================
# 工作流程模板（兩套版本）
# =============================
# mode: "redraw" 使用 keys "28" 與 "29"
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

# mode: "reverse" 使用 keys "25" 與 "26"
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
# 工具函数：保存 Base64 图片
# =============================
def save_base64_image(data_url, folder, prefix):
    try:
        header, encoded = data_url.split(",", 1)
    except Exception as e:
        return None, f"无效的图片数据: {e}"
    file_ext = "png"
    if "jpeg" in header or "jpg" in header:
        file_ext = "jpg"
    filename = f"{prefix}_{uuid.uuid4().hex}.{file_ext}"
    filepath = os.path.join(folder, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(encoded))
        return filepath, None
    except Exception as e:
        return None, str(e)

# =============================
# 工具函数：调用 ComfyUI API 与等待完成
# =============================
def queue_prompt(prompt):
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": prompt,
        "client_id": client_id
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 无法连接到 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    print("🕐 等待 ComfyUI 任务完成...")
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message.get("type") == "executing":
                    data = message.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任务完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 连接错误: {e}")

def get_history(prompt_id):
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print(f"📜 Debug: history API 响应 = {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 无法获取历史记录: {e}")
        return {}

def find_latest_png():
    png_files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 文件！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎞 找到最新的 .png 文件: {latest_png}")
    return latest_png

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 响应为空，改用文件搜索。")
        return find_latest_png()
    outputs = history.get("outputs", {})
    for key in ["27", "7"]:
        image_node = outputs.get(key, {})
        if "images" in image_node:
            for info in image_node["images"]:
                filename = info.get("filename")
                if filename and filename.lower().endswith(".png"):
                    print(f"🎞 从 API 获取图片文件名: {filename}")
                    return filename
    print("⚠️ /history API 未提供图片文件名，改用文件搜索。")
    return find_latest_png()

def move_output_files(prompt_id, target_dir):
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 无法获取图片文件名！")
        return None
    source_path = os.path.join(comfyui_output_dir, image_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，尝试搜索最新 png 文件。")
        image_filename = find_latest_png()
        if not image_filename:
            print("🚫 搜索不到 PNG 文件！")
            return None
        source_path = os.path.join(comfyui_output_dir, image_filename)
    target_path = os.path.join(target_dir, image_filename)
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已移动: {source_path} → {target_path}")
        return image_filename
    except Exception as e:
        print(f"❌ 移动失败: {e}")
        return None

# =============================
# Flask API Endpoint：/convert-image
# =============================
@app.route("/convert-image", methods=["POST"])
def convert_image():
    data = request.get_json(force=True)
    if not data or "originalImage" not in data or "maskImage" not in data:
        return jsonify({"error": "未提供原始图片或遮罩图片"}), 400

    # 保存原始图片与遮罩图片至临时文件夹
    orig_path, err = save_base64_image(data["originalImage"], temp_input_dir, "orig")
    if err:
        return jsonify({"error": f"原始图片保存错误: {err}"}), 500
    mask_path, err = save_base64_image(data["maskImage"], temp_input_dir, "mask")
    if err:
        return jsonify({"error": f"遮罩图片保存错误: {err}"}), 500

    # 新增：如果存在 "purePainting"（仅包含用户绘制部分，背景透明）则保存
    pure_path = None
    if "purePainting" in data:
        pure_path, err = save_base64_image(data["purePainting"], temp_input_dir, "pure")
        if err:
            return jsonify({"error": f"纯绘画图片保存错误: {err}"}), 500

    prompt_text = data.get("prompt", "").strip()
    if not prompt_text:
        return jsonify({"error": "提示词为空"}), 400

    try:
        cfg_scale = int(data.get("cfgScale", 7))
    except:
        cfg_scale = 7
    sampler_name = data.get("samplerName", "euler")
    scheduler = data.get("scheduler", "karras")
    seed_val = data.get("seed", "")
    try:
        seed = int(seed_val) if seed_val != "" else int(uuid.uuid4().int % 1000000)
    except:
        seed = int(uuid.uuid4().int % 1000000)

    mode = data.get("mode", "redraw").strip()  # "redraw" 或 "reverse"

    # 根据 mode 选择工作流程模板与目标目录
    if mode == "reverse":
        workflow_template = workflow_reverse_template
        target_dir = target_dir_reverse
    else:
        workflow_template = workflow_redraw_template
        target_dir = target_dir_redraw

    try:
        workflow = json.loads(workflow_template)
    except Exception as e:
        return jsonify({"error": "工作流程 JSON 格式错误", "details": str(e)}), 500

    # 修改工作流程参数
    workflow["2"]["inputs"]["text"] = prompt_text
    workflow["4"]["inputs"]["cfg"] = cfg_scale
    workflow["4"]["inputs"]["sampler_name"] = sampler_name
    workflow["4"]["inputs"]["scheduler"] = scheduler
    workflow["4"]["inputs"]["seed"] = seed

    # 设置原始图片与遮罩图片路径到工作流程中
    if mode == "reverse":
        workflow["25"]["inputs"]["image_path"] = orig_path
        workflow["26"]["inputs"]["image_path"] = mask_path
    else:
        workflow["28"]["inputs"]["image_path"] = orig_path
        workflow["29"]["inputs"]["image_path"] = mask_path

    print("🚀 发送工作流程到 ComfyUI：")
    print(json.dumps(workflow, indent=4, ensure_ascii=False))

    response = queue_prompt(workflow)
    if not response or "prompt_id" not in response:
        return jsonify({"error": "API 响应错误，请检查 ComfyUI 是否在运行"}), 500

    prompt_id = response["prompt_id"]
    client_id = response["client_id"]
    print(f"🆔 获取 prompt_id: {prompt_id}")

    wait_for_completion(prompt_id, client_id)

    # 增加等待时间，确保文件生成
    time.sleep(5)

    print("✅ 任务完成，开始移动输出图片。")
    output_filename = move_output_files(prompt_id, target_dir)
    if not output_filename:
        return jsonify({"error": "移动图片失败"}), 500

    # 返回图片 URL，使用外网域名构造
    image_url = EXTERNAL_URL + "/get_image/" + output_filename + f"?t={int(time.time())}"
    pure_painting_url = None
    if pure_path:
        pure_filename = os.path.basename(pure_path)
        target_pure_path = os.path.join(pure_painting_dir, pure_filename)
        try:
            shutil.copy(pure_path, target_pure_path)
            print(f"✅ 纯绘画图片已复制: {pure_path} → {target_pure_path}")
            pure_painting_url = EXTERNAL_URL + "/get_pure/" + pure_filename + f"?t={int(time.time())}"
        except Exception as e:
            print(f"❌ 纯绘画图片复制失败: {e}")
            return jsonify({"error": "纯绘画图片复制失败", "details": str(e)}), 500

    return jsonify({"image_url": image_url, "pure_painting_url": pure_painting_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    file_path_redraw = os.path.join(target_dir_redraw, filename)
    file_path_reverse = os.path.join(target_dir_reverse, filename)
    if os.path.exists(file_path_redraw):
        return send_from_directory(target_dir_redraw, filename)
    elif os.path.exists(file_path_reverse):
        return send_from_directory(target_dir_reverse, filename)
    else:
        return "文件不存在", 404

@app.route("/get_pure/<filename>", methods=["GET"])
def get_pure(filename):
    if os.path.exists(os.path.join(pure_painting_dir, filename)):
        return send_from_directory(pure_painting_dir, filename)
    else:
        return "文件不存在", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
