import json
import os
import shutil
import time
import websocket  # 確保已安裝 `websocket-client`
import urllib.request
import urllib.parse
import uuid

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address = "127.0.0.1:8188"                 # ComfyUI 伺服器位址
client_id = str(uuid.uuid4())                    # 產生唯一 client ID
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir = r"D:\大模型qcode"
os.makedirs(target_dir, exist_ok=True)           # 確保目標資料夾存在

# =============================
# 函式定義
# =============================
def queue_prompt(prompt):
    """
    發送工作流程(Workflow) JSON 到 ComfyUI 的 /prompt API，回傳包含 prompt_id 的結果。
    """
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None


def wait_for_completion(prompt_id):
    """
    透過 WebSocket 連線到 ComfyUI，持續監聽指定 prompt_id 的執行狀態，直到任務完成為止。
    """
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
                    # 當 node 為 None 且 prompt_id 匹配時，代表整個流程已結束
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")


def get_history(prompt_id):
    """
    透過 /history/<prompt_id> API 取得該任務的輸出紀錄，並回傳對應的 JSON。
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
    若 /history API 未提供有效檔名，則於 ComfyUI 輸出資料夾中搜尋最新的 .png 檔。
    """
    png_files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".png")]
    if not png_files:
        print("🚫 找不到任何 .png 檔案！")
        return None
    latest_png = max(png_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
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

    # 若還是找不到，就透過本機資料夾搜尋
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
# 以下為 API 工作流程 (Workflow) JSON
# =============================
prompt_text = """
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
      "image_path": "E:/sd_qr_output/optimized_qr_code.png",
      "RGBA": "false",
      "filename_text_extension": "true"
    },
    "class_type": "Image Load",
    "_meta": {
      "title": "圖像載入"
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

# 將 JSON 轉成 Python dict
prompt = json.loads(prompt_text)

# 以下根據需求對部分節點參數進行修改：
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

# QR code 圖片路徑 (ID=30)
# 這裡同樣可以使用 E:\\sd_qr_output\\optimized_qr_code.png
# 但需注意在 JSON 內要雙反斜線或改用 /
prompt["30"]["inputs"]["image_path"] = r"E:\sd_qr_output\optimized_qr_code.png"
#創意QRCODE控制網路
prompt["3"]["inputs"]["control_net_name"] = "sd1.5_qrcode.safetensors"

# =============================
# 送出任務給 ComfyUI 並處理結果
# =============================
print("🚀 發送工作流程到 ComfyUI...")
response = queue_prompt(prompt)

if not response or "prompt_id" not in response:
    print("❌ API 回應錯誤，請檢查 ComfyUI 是否在運行")
    exit()

prompt_id = response["prompt_id"]
print(f"🆔 取得 prompt_id: {prompt_id}")

# 等待 ComfyUI 任務完成
wait_for_completion(prompt_id)

# 搬移輸出的圖檔
move_output_files(prompt_id)
