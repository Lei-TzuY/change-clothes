import json
import os
import shutil
import time
import websocket  # 請確保已安裝 websocket-client (pip install websocket-client)
import urllib.request
import urllib.parse
import uuid

# =============================
# ComfyUI 伺服器與資料夾設定
# =============================
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器位址
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir = r"D:\大模型圖生線稿上色圖"
os.makedirs(target_dir, exist_ok=True)  # 確保目標資料夾存在

# =============================
# 函式定義
# =============================

def queue_prompt(prompt):
    """
    發送工作流程 (Workflow) JSON 到 ComfyUI 的 /prompt API，
    並回傳包含 prompt_id 與該任務專用 client_id 的結果。
    """
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": prompt,
        "client_id": client_id
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    """
    建立新的 WebSocket 連線監聽指定 prompt_id 的執行狀態。
    當收到 'executing' 訊息，且其中的 node = None (並且 prompt_id 相符) 時，表示該流程已完成。
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
    從 /history/<prompt_id> 中找出最終輸出的圖片檔名，
    如果無法從 API 找到，則改用檔案搜尋。
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
# 使用原始字串 (在前面加上 r) 以避免跳脫字元錯誤
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
      "text": "1girl, solo, long_hair, breasts, looking_at_viewer, blush, open_mouth, bangs, blue_eyes, simple_background, long_sleeves, white_background, bow, jewelry, upper_body, white_hair, hair_bow, earrings, parted_lips, two_side_up, black_bow, hair_intakes",
      "clip": [
        "1",
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
      "text": "mutated hands \nfingers, deformed,bad\nanatomy,disfigured,poorly drawn\nface,mutated,extra\nlimb,ugly,poorly drawn\nhands,missing limb,floating\nlimbs,disconnected\nlimbs,malformed hands,out of\nfocus,long neck,long body,\n",
      "clip": [
        "1",
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
      "seed": 114978600424028,
      "steps": 20,
      "cfg": 8,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": [
        "1",
        0
      ],
      "positive": [
        "18",
        0
      ],
      "negative": [
        "18",
        1
      ],
      "latent_image": [
        "34",
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
  "18": {
    "inputs": {
      "strength": 1.5,
      "start_percent": 0,
      "end_percent": 1,
      "positive": [
        "2",
        0
      ],
      "negative": [
        "3",
        0
      ],
      "control_net": [
        "19",
        0
      ],
      "image": [
        "47",
        0
      ],
      "vae": [
        "9",
        0
      ]
    },
    "class_type": "ControlNetApplyAdvanced",
    "_meta": {
      "title": "ControlNet應用(進階)"
    }
  },
  "19": {
    "inputs": {
      "control_net_name": "control_sd15_canny.pth"
    },
    "class_type": "ControlNetLoader",
    "_meta": {
      "title": "ControlNet載入器"
    }
  },
  "34": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 512,
      "height": 512,
      "crop": "disabled",
      "samples": [
        "37",
        0
      ]
    },
    "class_type": "LatentUpscale",
    "_meta": {
      "title": "Latent縮放"
    }
  },
  "37": {
    "inputs": {
      "pixels": [
        "48",
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
  "44": {
    "inputs": {
      "images": [
        "47",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "47": {
    "inputs": {
      "low_threshold": 100,
      "high_threshold": 200,
      "resolution": 512,
      "image": [
        "51",
        0
      ]
    },
    "class_type": "CannyEdgePreprocessor",
    "_meta": {
      "title": "Canny線條預處理器"
    }
  },
  "48": {
    "inputs": {
      "image_path": "\"D:\\comfyui\\ComfyUI_windows_portable\\ComfyUI\\output\\ComfyUI_00011_.png\""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {
      "title": "Load Image Path or URL"
    }
  },
  "49": {
    "inputs": {
      "images": [
        "48",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "50": {
    "inputs": {
      "images": [
        "51",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "51": {
    "inputs": {
      "image_path": "\"C:\\Users\\User\\Desktop\\蹲姿.png\""
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {
      "title": "Load Image Path or URL"
    }
  }
}
"""

# 將 JSON 轉成 Python dict
try:
    prompt = json.loads(prompt_text)
except json.decoder.JSONDecodeError as e:
    print(f"❌ JSON 格式錯誤: {e}")
    exit()

# 修改其他參數，確保 prompt 結構符合 ComfyUI 的預期
prompt["9"]["inputs"]["vae_name"] = "kl-f8-anime2.safetensors"
prompt["1"]["inputs"]["ckpt_name"] = "meinamix_v12Final.safetensors"
prompt["2"]["inputs"]["text"] = "1girl, solo, long_hair, breasts, looking_at_viewer, blush, open_mouth, bangs, blue_eyes, simple_background, long_sleeves, white_background, bow, jewelry, upper_body, white_hair, hair_bow, earrings, parted_lips, two_side_up, black_bow, hair_intakes"
prompt["4"]["inputs"]["cfg"] = 7
prompt["4"]["inputs"]["sampler_name"] = "dpmpp_2m_sde"
prompt["4"]["inputs"]["scheduler"] = "karras"
prompt["4"]["inputs"]["denoise"] = 1
prompt["4"]["inputs"]["seed"] = 87
# 參考圖上傳
prompt["48"]["inputs"]["image_path"] = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output\ComfyUI_00011_.png"
# 線搞圖上傳
prompt["51"]["inputs"]["image_path"] = r"C:\Users\User\Desktop\蹲姿.png"
#線搞參數設定
prompt["47"]["inputs"]["low_threshold"] = 100
prompt["47"]["inputs"]["high_threshold"] = 200
prompt["18"]["inputs"]["strength"] = 1.5
prompt["18"]["inputs"]["start_percent"] = 0
prompt["18"]["inputs"]["end_percent"] = 1
#線搞控制網路
prompt["19"]["inputs"]["control_net_name"] = "control_sd15_canny.pth"
# =============================
# 送出任務給 ComfyUI 並處理結果
# =============================
print("🚀 發送工作流程到 ComfyUI...")
response = queue_prompt(prompt)
if not response or "prompt_id" not in response:
    print("❌ API 回應錯誤，請檢查 ComfyUI 是否在運行")
    exit()

prompt_id = response["prompt_id"]
client_id = response["client_id"]
print(f"🆔 取得 prompt_id: {prompt_id}")

# 等待流程完成，不再讀取或比較執行時間
wait_for_completion(prompt_id, client_id)

print("✅ 任務正常完成，將搬移輸出結果。")
move_output_files(prompt_id)
