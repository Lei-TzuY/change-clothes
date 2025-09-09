import json
import os
import shutil
import time
import websocket  # 請確保已安裝 websocket-client 套件 (pip install websocket-client)
import urllib.request
import urllib.parse
import uuid

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器位址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"  # ComfyUI 輸出資料夾路徑
target_dir = r"D:\Lora大模型局部重繪反轉"  # 目標資料夾路徑，用來存放搬移後的圖片
os.makedirs(target_dir, exist_ok=True)  # 若目標資料夾不存在則建立

# =============================
# 函式定義
# =============================

def queue_prompt(prompt):
    """
    將工作流程 (Workflow) JSON 送往 ComfyUI 的 /prompt API，
    並回傳包含 prompt_id 與任務專用 client_id 的結果。
    """
    client_id = str(uuid.uuid4())  # 生成唯一的 client_id
    payload = {
        "prompt": prompt,
        "client_id": client_id
    }
    data = json.dumps(payload).encode("utf-8")  # 將 payload 轉為 JSON 並編碼
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id  # 將 client_id 加入回傳結果中
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    """
    建立 WebSocket 連線以監聽指定 prompt_id 的執行狀態。
    當收到 'executing' 訊息，且其中的 node 為 None 且 prompt_id 相符時，
    表示該流程已完成。
    """
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    print("🕐 等待 ComfyUI 任務完成...")
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()  # 接收 WebSocket 訊息
            if isinstance(out, str):
                message = json.loads(out)
                if message.get("type") == "executing":
                    data = message.get("data", {})
                    # 當 node 為 None 且 prompt_id 符合時，代表流程完成
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")

def get_history(prompt_id):
    """
    透過 /history/<prompt_id> API 取得該任務的歷史輸出紀錄，
    並回傳相對應的 JSON 資料。
    """
    url = f"http://{server_address}/history/{prompt_id}"
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
    若 /history API 未提供有效檔名，則在 ComfyUI 輸出資料夾中
    搜尋最新建立的 .png 檔案。
    """
    png_files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    # 根據檔案建立時間取得最新的檔案
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎞 找到最新的 .png 檔案: {latest_png}")
    return latest_png

def get_final_image_filename(prompt_id):
    """
    從 /history/<prompt_id> 的回應中找出最終輸出的圖片檔名，
    若找不到則改用檔案搜尋方式取得最新 .png 檔案。
    """
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_png()
    outputs = history.get("outputs", {})
    image_node = outputs.get("7", {})
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
    取得最終輸出的圖片檔名後，將該 .png 檔從 ComfyUI 輸出資料夾
    搬移至指定目標資料夾中。
    """
    image_filename = get_final_image_filename(prompt_id)
    if not image_filename:
        print("🚫 無法取得圖片檔案名稱！")
        return
    source_path = os.path.join(comfyui_output_dir, image_filename)
    target_path = os.path.join(target_dir, image_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")

# =============================
# 定義 API 工作流程 (Workflow) JSON
# =============================
# 使用原始字串 (raw string) 以避免跳脫字元被預先處理，導致 JSONDecodeError
prompt_text = r"""
{
  "1": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Checkpoint載入器(簡易)"
    }
  },
  "2": {
    "inputs": {
      "text": "a garden",
      "clip": [
        "25",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "3": {
    "inputs": {
      "text": "",
      "clip": [
        "25",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "4": {
    "inputs": {
      "seed": 422329407793519,
      "steps": 50,
      "cfg": 7,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": [
        "25",
        0
      ],
      "positive": [
        "2",
        0
      ],
      "negative": [
        "3",
        0
      ],
      "latent_image": [
        "14",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "K採樣器"
    }
  },
  "7": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": [
        "8",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "儲存圖像"
    }
  },
  "8": {
    "inputs": {
      "samples": [
        "4",
        0
      ],
      "vae": [
        "9",
        0
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE解碼"
    }
  },
  "9": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "VAE載入器"
    }
  },
  "13": {
    "inputs": {
      "pixels": [
        "27",
        0
      ],
      "vae": [
        "9",
        0
      ]
    },
    "class_type": "VAEEncode",
    "_meta": {
      "title": "VAE編碼"
    }
  },
  "14": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 512,
      "height": 512,
      "crop": "disabled",
      "samples": [
        "15",
        0
      ]
    },
    "class_type": "LatentUpscale",
    "_meta": {
      "title": "Latent縮放"
    }
  },
  "15": {
    "inputs": {
      "samples": [
        "21",
        0
      ],
      "mask": [
        "23",
        0
      ]
    },
    "class_type": "SetLatentNoiseMask",
    "_meta": {
      "title": "設定Latent噪聲遮罩"
    }
  },
  "19": {
    "inputs": {
      "channel": "red",
      "image": [
        "26",
        0
      ]
    },
    "class_type": "ImageToMask",
    "_meta": {
      "title": "圖像到遮罩"
    }
  },
  "21": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 512,
      "height": 512,
      "crop": "disabled",
      "samples": [
        "13",
        0
      ]
    },
    "class_type": "LatentUpscale",
    "_meta": {
      "title": "Latent縮放"
    }
  },
  "22": {
    "inputs": {
      "mask": [
        "23",
        0
      ]
    },
    "class_type": "MaskToImage",
    "_meta": {
      "title": "遮罩到圖像"
    }
  },
  "23": {
    "inputs": {
      "mask": [
        "19",
        0
      ]
    },
    "class_type": "InvertMask",
    "_meta": {
      "title": "遮罩反轉"
    }
  },
  "24": {
    "inputs": {
      "images": [
        "22",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "25": {
    "inputs": {
      "lora_name": "asuna_(stacia)-v1.5.safetensors",
      "strength_model": 1,
      "strength_clip": 1,
      "model": [
        "1",
        0
      ],
      "clip": [
        "1",
        1
      ]
    },
    "class_type": "LoraLoader",
    "_meta": {
      "title": "LoRA載入器"
    }
  },
  "26": {
    "inputs": {
      "image_path": "\"./input/example.png\""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {
      "title": "Load Image Path or URL"
    }
  },
  "27": {
    "inputs": {
      "image_path": "\"./input/example.png\""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {
      "title": "Load Image Path or URL"
    }
  }
}
"""

# 將 JSON 字串轉換成 Python dict 物件
try:
    prompt = json.loads(prompt_text)
except json.decoder.JSONDecodeError as e:
    print(f"❌ JSON 格式錯誤: {e}")
    exit()

# =============================
# 修改 prompt 中的參數，確保結構符合 ComfyUI 的預期
# =============================
prompt["9"]["inputs"]["vae_name"] = "kl-f8-anime2.safetensors"
prompt["1"]["inputs"]["ckpt_name"] = "meinamix_v12Final.safetensors"
prompt["2"]["inputs"]["text"] = "garden"
prompt["4"]["inputs"]["cfg"] = 7
prompt["4"]["inputs"]["sampler_name"] = "dpmpp_2m_sde"
prompt["4"]["inputs"]["scheduler"] = "karras"
prompt["4"]["inputs"]["denoise"] = 0.7
prompt["4"]["inputs"]["seed"] = 87
# 原始圖 (注意：此處路徑為原始字串)
prompt["27"]["inputs"]["image_path"] = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output\ComfyUI_00008_.png"
# 遮罩路徑 (注意：此處路徑為原始字串)
prompt["26"]["inputs"]["image_path"] = r"C:\Users\User\Desktop\processed_mask.png"
prompt["25"]["inputs"]["lora_name"] = "super-vanilla-newlora-ver1-p.safetensors"
prompt["25"]["inputs"]["strength_model"] = 1
prompt["25"]["inputs"]["strength_clip"] = 0.8
# =============================
# 發送任務給 ComfyUI 並處理結果
# =============================
print("🚀 發送工作流程到 ComfyUI...")
response = queue_prompt(prompt)
if not response or "prompt_id" not in response:
    print("❌ API 回應錯誤，請檢查 ComfyUI 是否正在運行")
    exit()

prompt_id = response["prompt_id"]
client_id = response["client_id"]
print(f"🆔 取得 prompt_id: {prompt_id}")

# 等待工作流程完成
wait_for_completion(prompt_id, client_id)

print("✅ 任務正常完成，開始搬移輸出結果。")
move_output_files(prompt_id)
