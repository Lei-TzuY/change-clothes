import os
import json
import shutil
import time
import uuid
import base64
import urllib.request
import urllib.parse
import requests
import websocket  # 確保已安裝 `websocket-client`
import qrcode
from io import BytesIO
from PIL import Image, PngImagePlugin

# ========================
# A. 基本設定
# ========================
# ComfyUI 伺服器位址（REST + WebSocket）
SERVER_ADDRESS = "127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())  # 產生唯一 client ID

# ComfyUI 輸出目錄與目標資料夾 (最後成品搬移至此)
COMFYUI_OUTPUT_DIR = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
TARGET_DIR = r"D:\大模型qcode"
os.makedirs(TARGET_DIR, exist_ok=True)

# 用於暫存產生之 QR Code 的資料夾 & 檔名
QR_OUTPUT_FOLDER = r"D:\大模型qcode"
os.makedirs(QR_OUTPUT_FOLDER, exist_ok=True)
QR_CODE_PATH = os.path.join(QR_OUTPUT_FOLDER, "optimized_qr_code.png")

# 預設要放到 QR Code 裡的網址 (直接指定)
DEFAULT_QR_CODE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# ========================
# B. 生成 QR Code
# ========================
def generate_qr_code(url, output_file):
    """
    生成一個容易掃描的 QR Code 並儲存。
    - url: 要放在 QR Code 的連結
    - output_file: 輸出檔案路徑
    """
    # version 3 + H 級容錯，可再視需求調整
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

# ========================
# C. ComfyUI 互動相關函式
# ========================
def queue_prompt(prompt):
    """
    發送工作流程(Workflow) JSON 到 ComfyUI 的 /prompt API，
    回傳包含 prompt_id 的結果。
    """
    payload = {"prompt": prompt, "client_id": CLIENT_ID}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{SERVER_ADDRESS}/prompt"

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id):
    """
    透過 WebSocket 連線到 ComfyUI，
    持續監聽指定 prompt_id 的執行狀態，直到任務完成為止。
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
                    # 當 node 為 None 且 prompt_id 匹配時，代表整個流程已結束
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")

def get_history(prompt_id):
    """
    透過 /history/<prompt_id> API 取得該任務的輸出紀錄，
    並回傳對應的 JSON。
    """
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
    """
    若 /history API 未提供有效檔名，則於 ComfyUI 輸出資料夾中搜尋最新的 .png 檔。
    """
    png_files = [f for f in os.listdir(COMFYUI_OUTPUT_DIR) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(COMFYUI_OUTPUT_DIR, f)))
    print(f"🎞 找到最新的 .png 檔案: {latest_png}")
    return latest_png

def get_final_image_filename(prompt_id):
    """
    從 /history/<prompt_id> 中找出最終輸出的圖片檔名。
    如果無法從 API 找到，則改用 find_latest_png()。
    """
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_png()

    # 節點 31 通常是 SaveImage 節點，調整為你實際的輸出節點 ID
    outputs = history.get("outputs", {})
    image_node = outputs.get("31", {})

    # 根據 ComfyUI 的回傳格式，儲存圖像時通常為 "images" 這個 key
    if "images" in image_node:
        for info in image_node["images"]:
            filename = info.get("filename")
            if filename and filename.lower().endswith(".png"):
                print(f"🎞 從 API 取得圖片檔名: {filename}")
                return filename

    print("⚠️ /history API 未提供圖片檔名，改用檔案搜尋。")
    return find_latest_png()

def move_output_files(prompt_id):
    """
    將 get_final_image_filename() 找到的 .png 檔搬移到指定的目標資料夾。
    """
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 無法取得圖片檔案名稱！")
        return

    source_path = os.path.join(COMFYUI_OUTPUT_DIR, image_filename)
    target_path = os.path.join(TARGET_DIR, image_filename)

    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return

    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")

# =============================
# D. 工作流程 (Workflow) JSON
# =============================
# 為避免轉義問題，路徑皆以 "E:/" 或正斜線表示
# 下面的 JSON 範例參考了成功案例，並修正節點 30 為 VHS_LoadImagePath 節點
prompt_text = r"""
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
      "b2": 1.4000000000000001,
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
"""

# =============================
# E. 主程式流程
# =============================
if __name__ == "__main__":
    # 1) 生成 QR Code
    generate_qr_code(DEFAULT_QR_CODE_URL, QR_CODE_PATH)

    # 2) 將 Workflow JSON 轉成 Python dict
    prompt = json.loads(prompt_text)

    # 3) 根據需求對部分節點參數進行修改
    # VAE 設定
    prompt["17"]["inputs"]["vae_name"] = "kl-f8-anime2.safetensors"

    # Checkpoint 設定
    prompt["26"]["inputs"]["ckpt_name"] = "meinamix_v12Final.safetensors"

    # 提示詞 (正向) 設定，對應 CLIPTextEncode 節點 ID=10
    prompt["10"]["inputs"]["text"] = "house"

    # KSampler 參數
    prompt["9"]["inputs"]["cfg"] = 6
    prompt["9"]["inputs"]["sampler_name"] = "dpmpp_2m_sde"
    prompt["9"]["inputs"]["scheduler"] = "karras"
    prompt["9"]["inputs"]["seed"] = 87

    # ControlNet 參數 (ID=2)
    prompt["2"]["inputs"]["strength"] = 1.3
    prompt["2"]["inputs"]["start_percent"] = 0.1
    prompt["2"]["inputs"]["end_percent"] = 0.9

    # 載入 QR code 圖片路徑 (ID=30)
    prompt["30"]["inputs"]["image"] = QR_CODE_PATH.replace("\\", "/")
    #創意QRCODE控制網路
    prompt["3"]["inputs"]["control_net_name"] = "sd1.5_qrcode.safetensors"

    # 4) 送出任務給 ComfyUI
    print("🚀 發送工作流程到 ComfyUI...")
    response = queue_prompt(prompt)
    if not response or "prompt_id" not in response:
        print("❌ API 回應錯誤，請檢查 ComfyUI 是否在運行")
        exit()

    prompt_id = response["prompt_id"]
    print(f"🆔 取得 prompt_id: {prompt_id}")

    # 5) 等待 ComfyUI 任務完成
    wait_for_completion(prompt_id)

    # 6) 搬移輸出的圖檔
    move_output_files(prompt_id)
