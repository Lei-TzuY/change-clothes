import os
import json
import shutil
import time
import uuid
import base64
import urllib.request
import urllib.error
import websocket
import qrcode

from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# =============================
# 基本設定
# =============================

# ComfyUI 伺服器位址（請確認此位址與埠號正確）
SERVER_ADDRESS = "127.0.0.1:8188"

# 定義全域 CLIENT_ID，用於識別本服務發送的請求（生成一次即可）
CLIENT_ID = str(uuid.uuid4())

# ComfyUI 的輸出目錄（儲存生成圖片的目錄）
COMFYUI_OUTPUT_DIR = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"

# 目標目錄，用來儲存最終搬移過來的圖片
TARGET_DIR = r"D:\大模型qcode"
os.makedirs(TARGET_DIR, exist_ok=True)

# 用於暫存生成或上傳的 QR Code 圖片的資料夾
TEMP_FOLDER = r"D:\大模型qcode\temp"
os.makedirs(TEMP_FOLDER, exist_ok=True)

# 前端不使用預設 QR Code 網址，由前端傳入
DEFAULT_QR_CODE_URL = ""

# =============================
# 外網域名（用於回傳圖片 URL）
# =============================
EXTERNAL_URL = "https://qrcode.picturesmagician.com"

# =============================
# A. 生成 QR Code 的函式
# =============================
def generate_qr_code(url, output_file):
    """
    根據傳入的 URL 生成 QR Code 並儲存至指定檔案
    """
    qr = qrcode.QRCode(
        version=3,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2
    )
    qr.add_data(url, optimize=True)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_file)
    print(f"✅ QR Code 已儲存: {output_file}")

# =============================
# B. 與 ComfyUI 互動的相關函式
# =============================
def queue_prompt(prompt):
    """
    發送請求到 ComfyUI 的 /prompt API
    """
    payload = {"prompt": prompt, "client_id": CLIENT_ID}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{SERVER_ADDRESS}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = CLIENT_ID
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id):
    """
    使用 WebSocket 監聽 ComfyUI 任務進度，直到任務完成
    """
    ws_url = f"ws://{SERVER_ADDRESS}/ws?clientId={CLIENT_ID}"
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
        print(f"❌ WebSocket 連線錯誤: {e}")

def get_history(prompt_id):
    url = f"http://{SERVER_ADDRESS}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print(f"📜 Debug: history API 回應 = {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def find_latest_png():
    png_files = [f for f in os.listdir(COMFYUI_OUTPUT_DIR) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(COMFYUI_OUTPUT_DIR, f)))
    print(f"🎞 找到最新的 .png 檔案: {latest_png}")
    return latest_png

def get_final_image_filename(prompt_id):
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_png()
    outputs = history.get("outputs", {})
    # 假設生成圖片的節點 ID 為 "31"
    image_node = outputs.get("31", {})
    if "images" in image_node:
        for info in image_node["images"]:
            filename = info.get("filename")
            if filename and filename.lower().endswith(".png"):
                print(f"🎞 從 API 取得圖片檔名: {filename}")
                return filename
    print("⚠️ /history API 未提供圖片檔名，改用檔案搜尋。")
    return find_latest_png()

def move_output_files(prompt_id):
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 無法取得圖片檔案名稱！")
        return None
    source_path = os.path.join(COMFYUI_OUTPUT_DIR, image_filename)
    target_path = os.path.join(TARGET_DIR, image_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return None
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
        return image_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None

# =============================
# C. Flask API Endpoint：/convert-image
# =============================
@app.route("/convert-image", methods=["POST"])
def convert_image_endpoint():
    data = request.get_json(force=True)
    if not data or "prompt" not in data:
        return jsonify({"error": "缺少必要的參數"}), 400

    conversionType = data.get("conversionType", "text").strip()  # "text" 或 "image"
    if conversionType == "text":
        qrUrl = data.get("qrUrl", "").strip()
        if not qrUrl:
            return jsonify({"error": "請提供 QR Code 網址！"}), 400
        qr_output_file = os.path.join(TEMP_FOLDER, f"qr_{uuid.uuid4().hex}.png")
        try:
            generate_qr_code(qrUrl, qr_output_file)
        except Exception as e:
            return jsonify({"error": f"QR Code 生成失敗: {e}"}), 500
        qr_image_path = qr_output_file
    elif conversionType == "image":
        qr_image_b64 = data.get("qrImage", "").strip()
        if not qr_image_b64:
            return jsonify({"error": "圖生模式下未提供圖片"}), 400
        try:
            header, encoded = qr_image_b64.split(",", 1)
        except Exception as e:
            return jsonify({"error": f"無效的圖片資料: {e}"}), 400
        file_ext = "png"
        if "jpeg" in header or "jpg" in header:
            file_ext = "jpg"
        qr_output_file = os.path.join(TEMP_FOLDER, f"qr_{uuid.uuid4().hex}.{file_ext}")
        try:
            with open(qr_output_file, "wb") as f:
                f.write(base64.b64decode(encoded))
        except Exception as e:
            return jsonify({"error": f"圖片儲存失敗: {e}"}), 500
        qr_image_path = qr_output_file
    else:
        return jsonify({"error": "無效的 conversionType"}), 400

    prompt_text = data.get("prompt", "").strip()
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

    print("收到參數設定：")
    print(f"CFG 強度: {cfg_scale}")
    print(f"採樣器: {sampler_name}")
    print(f"調度器: {scheduler}")
    print(f"種子: {seed}")
    print(f"提示詞: {prompt_text}")

    workflow = json.loads(r"""
{
  "2": {
    "inputs": {
      "strength": 1.3,
      "start_percent": 0.1,
      "end_percent": 0.9,
      "positive": [
        "10",
        0
      ],
      "negative": [
        "11",
        0
      ],
      "control_net": [
        "3",
        0
      ],
      "image": [
        "30",
        0
      ]
    },
    "class_type": "ControlNetApplyAdvanced",
    "_meta": {
      "title": "ControlNet應用(進階)"
    }
  },
  "3": {
    "inputs": {
      "control_net_name": "sd1.5_qrcode.safetensors"
    },
    "class_type": "ControlNetLoader",
    "_meta": {
      "title": "ControlNet載入器"
    }
  },
  "8": {
    "inputs": {
      "b1": 1.3,
      "b2": 1.4,
      "s1": 0.9,
      "s2": 0.2,
      "model": [
        "26",
        0
      ]
    },
    "class_type": "FreeU_V2",
    "_meta": {
      "title": "FreeU_V2"
    }
  },
  "9": {
    "inputs": {
      "seed": 249753754870844,
      "steps": 50,
      "cfg": 6,
      "sampler_name": "dpmpp_2m_sde",
      "scheduler": "karras",
      "denoise": 1,
      "model": [
        "8",
        0
      ],
      "positive": [
        "2",
        0
      ],
      "negative": [
        "2",
        1
      ],
      "latent_image": [
        "12",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "K採樣器"
    }
  },
  "10": {
    "inputs": {
      "text": "house",
      "clip": [
        "26",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "11": {
    "inputs": {
      "text": "embedding:EasyNegative, embedding:bad_prompt_version2-neg, embedding:verybadimagenegative_v1.3, ",
      "clip": [
        "26",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "12": {
    "inputs": {
      "width": [
        "25",
        0
      ],
      "height": [
        "25",
        0
      ],
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage",
    "_meta": {
      "title": "空Latent"
    }
  },
  "13": {
    "inputs": {
      "image": [
        "30",
        0
      ]
    },
    "class_type": "GetImageSize+",
    "_meta": {
      "title": "🔧 Get Image Size"
    }
  },
  "15": {
    "inputs": {
      "samples": [
        "9",
        0
      ],
      "vae": [
        "17",
        0
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE解碼"
    }
  },
  "16": {
    "inputs": {
      "images": [
        "15",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "17": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "VAE載入器"
    }
  },
  "25": {
    "inputs": {
      "value": 860
    },
    "class_type": "INTConstant",
    "_meta": {
      "title": "INT Constant"
    }
  },
  "26": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Checkpoint載入器(簡易)"
    }
  },
  "30": {
    "inputs": {
      "image": "E:/sd_qr_output/optimized_qr_code.png",
      "force_size": "Disabled",
      "custom_width": 512,
      "custom_height": 512
    },
    "class_type": "VHS_LoadImagePath",
    "_meta": {
      "title": "Load Image (Path)"
    }
  },
  "31": {
    "inputs": {
      "filename_prefix": "qrcode",
      "images": [
        "15",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "儲存圖像"
    }
  }
}
""")
    workflow["10"]["inputs"]["text"] = prompt_text
    workflow["9"]["inputs"]["cfg"] = cfg_scale
    workflow["9"]["inputs"]["sampler_name"] = sampler_name
    workflow["9"]["inputs"]["scheduler"] = scheduler
    workflow["9"]["inputs"]["seed"] = seed
    # 將節點 "30" 的 image 參數更新為 QR Code 圖片路徑（轉換路徑分隔符）
    workflow["30"]["inputs"]["image"] = qr_image_path.replace("\\", "/")
    
    print("🚀 發送工作流程到 ComfyUI：")
    print(json.dumps(workflow, indent=4, ensure_ascii=False))
    
    response = queue_prompt(workflow)
    if not response or "prompt_id" not in response:
        return jsonify({"error": "API 回應錯誤，請檢查 ComfyUI 是否在運行"}), 500
    
    prompt_id = response["prompt_id"]
    print(f"🆔 取得 prompt_id: {prompt_id}")
    
    wait_for_completion(prompt_id)
    
    print("✅ 任務已完成，開始搬移輸出圖片。")
    output_filename = move_output_files(prompt_id)
    if not output_filename:
        return jsonify({"error": "搬移圖片失敗"}), 500
    
    image_url = EXTERNAL_URL + "/get_image/" + output_filename + f"?t={int(time.time())}"
    return jsonify({"image_url": image_url})

@app.route("/get_image/<filename>", methods=["GET"])
def get_image(filename):
    return send_from_directory(TARGET_DIR, filename)

# 新增 /image_to_image 路由，供 ComfyUI 在工作流程中讀取圖片檔案
@app.route("/image_to_image", methods=["POST"])
def load_image():
    data = request.get_json(force=True)
    image_path = data.get("image")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "圖像路徑不存在"}), 404
    ext = os.path.splitext(image_path)[1].lower()
    mimetype = "image/png" if ext == ".png" else "image/jpeg"
    with open(image_path, "rb") as f:
        content = f.read()
    return content, 200, {"Content-Type": mimetype}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=False)
