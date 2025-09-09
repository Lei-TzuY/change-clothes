import json
import os
import shutil
import time
import websocket  # 確保安裝 `websocket-client`
import urllib.request
import urllib.parse
import uuid

# ComfyUI 伺服器位址
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())  # 產生唯一 client ID

# ComfyUI 輸出與目標資料夾
comfyui_output_dir = "D:/comfyui/ComfyUI_windows_portable/ComfyUI/output/"
target_dir = "D:/Hunyuan_txt2video_dataset/"
os.makedirs(target_dir, exist_ok=True)  # 確保目標資料夾存在


def queue_prompt(prompt):
    """發送請求到 ComfyUI API"""
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())


def wait_for_completion(prompt_id):
    """透過 WebSocket 監聽 ComfyUI，直到任務完成"""
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"

    try:
        ws = websocket.create_connection(ws_url)
        print("🕐 等待 ComfyUI 任務完成...")

        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message["type"] == "executing":
                    data = message["data"]
                    if data["node"] is None and data["prompt_id"] == prompt_id:
                        print("✅ 任務已完成！")
                        break  # 任務執行結束
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")


def get_history(prompt_id):
    """從 /history API 取得最終輸出的檔案名稱"""
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as response:
            history = json.loads(response.read())
        print(f"📜 Debug: history API 回應 = {json.dumps(history, indent=4)}")  # 🔹 檢查 API 回應
        return history.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得 API 歷史記錄: {e}")
        return {}


def get_final_video_filename(prompt_id):
    """取得 VHS_VideoCombine 產出的 MP4 檔案名稱"""
    history = get_history(prompt_id)
    
    # 如果 API 回傳空的 history，則改用檔案搜尋
    if not history:
        print("⚠️ API 沒回傳 MP4，改用檔案搜尋。")
        return find_latest_mp4()
    
    print(f"🔍 Debug: history = {json.dumps(history, indent=4)}")

    # 🔍 嘗試從 `VHS_VideoCombine` (`78` 節點) 查找 MP4
    video_node = history.get("outputs", {}).get("78", {})
    if "gifs" in video_node:
        for video in video_node["gifs"]:
            print(f"🎬 Found video from API: {video['filename']}")
            if video["filename"].endswith(".mp4"):
                return video["filename"]  # 直接返回 MP4 檔案名

    print("⚠️ API 沒找到 MP4，改用檔案搜尋。")
    return find_latest_mp4()  # 改用檔案搜尋


def find_latest_mp4():
    """從 ComfyUI 輸出資料夾尋找最新的 MP4 檔案"""
    mp4_files = [f for f in os.listdir(comfyui_output_dir) if f.endswith(".mp4")]
    if not mp4_files:
        print("🚫 找不到 MP4 檔案！")
        return None
    latest_mp4 = max(mp4_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎬 找到最新 MP4: {latest_mp4}")
    return latest_mp4


def move_output_files(prompt_id):
    """搬移 get_final_video_filename() 找到的 MP4 檔案"""
    mp4_filename = get_final_video_filename(prompt_id)
    
    if not mp4_filename:
        print("🚫 無法從 API 或檔案搜尋獲取 MP4 檔案名稱！")
        return

    source_path = os.path.join(comfyui_output_dir, mp4_filename)
    target_path = os.path.join(target_dir, mp4_filename)

    # 確保 MP4 存在再搬移
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法移動！")
        return

    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已移動: {source_path} → {target_path}")
    except Exception as e:
        print(f"❌ 移動失敗: {e}")
#This is the ComfyUI api prompt format.

#If you want it for a specific workflow you can "enable dev mode options"
#in the settings of the UI (gear beside the "Queue Size: ") this will enable
#a button on the UI to save workflows in api format.

#keep in mind ComfyUI is pre alpha software so this format will change a bit.

#this is the one for the default workflow
prompt_text = """
{
  "10": {
    "inputs": {
      "vae_name": "hunyuan_video_vae_bf16.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "VAE載入器"
    }
  },
  "11": {
    "inputs": {
      "clip_name1": "clip_l.safetensors",
      "clip_name2": "llava_llama3_fp8_scaled.safetensors",
      "type": "hunyuan_video",
      "device": "default"
    },
    "class_type": "DualCLIPLoader",
    "_meta": {
      "title": "雙CLIP載入器"
    }
  },
  "12": {
    "inputs": {
      "unet_name": "hunyuan_video_t2v_720p_bf16.safetensors",
      "weight_dtype": "default"
    },
    "class_type": "UNETLoader",
    "_meta": {
      "title": "UNET載入器"
    }
  },
  "13": {
    "inputs": {
      "noise": [
        "25",
        0
      ],
      "guider": [
        "22",
        0
      ],
      "sampler": [
        "16",
        0
      ],
      "sigmas": [
        "17",
        0
      ],
      "latent_image": [
        "45",
        0
      ]
    },
    "class_type": "SamplerCustomAdvanced",
    "_meta": {
      "title": "自定义采样器（高级）"
    }
  },
  "16": {
    "inputs": {
      "sampler_name": "euler"
    },
    "class_type": "KSamplerSelect",
    "_meta": {
      "title": "K采样器选择"
    }
  },
  "17": {
    "inputs": {
      "scheduler": "simple",
      "steps": 20,
      "denoise": 1,
      "model": [
        "12",
        0
      ]
    },
    "class_type": "BasicScheduler",
    "_meta": {
      "title": "基本调度器"
    }
  },
  "22": {
    "inputs": {
      "model": [
        "67",
        0
      ],
      "conditioning": [
        "26",
        0
      ]
    },
    "class_type": "BasicGuider",
    "_meta": {
      "title": "基本引导器"
    }
  },
  "25": {
    "inputs": {
      "noise_seed": 1003301849609304
    },
    "class_type": "RandomNoise",
    "_meta": {
      "title": "随机噪波"
    }
  },
  "26": {
    "inputs": {
      "guidance": 6,
      "conditioning": [
        "44",
        0
      ]
    },
    "class_type": "FluxGuidance",
    "_meta": {
      "title": "Flux引导"
    }
  },
  "44": {
    "inputs": {
      "text": "anime style anime girl with massive fennec ears and one big fluffy tail, she has blonde hair long hair blue eyes wearing a pink sweater and a long blue skirt walking in a beautiful outdoor scenery with snow mountains in the background",
      "clip": [
        "11",
        0
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "45": {
    "inputs": {
      "width": 512,
      "height": 512,
      "length": 73,
      "batch_size": 1
    },
    "class_type": "EmptyHunyuanLatentVideo",
    "_meta": {
      "title": "空Latent视频（混元）"
    }
  },
  "67": {
    "inputs": {
      "shift": 7,
      "model": [
        "12",
        0
      ]
    },
    "class_type": "ModelSamplingSD3",
    "_meta": {
      "title": "采样算法（SD3）"
    }
  },
  "73": {
    "inputs": {
      "tile_size": 256,
      "overlap": 64,
      "temporal_size": 64,
      "temporal_overlap": 8,
      "samples": [
        "13",
        0
      ],
      "vae": [
        "10",
        0
      ]
    },
    "class_type": "VAEDecodeTiled",
    "_meta": {
      "title": "VAE分塊解碼"
    }
  },
  "78": {
    "inputs": {
      "frame_rate": 24,
      "loop_count": 0,
      "filename_prefix": "渾元video",
      "format": "video/h264-mp4",
      "pix_fmt": "yuv420p",
      "crf": 19,
      "save_metadata": true,
      "trim_to_audio": false,
      "pingpong": false,
      "save_output": true,
      "images": [
        "73",
        0
      ]
    },
    "class_type": "VHS_VideoCombine",
    "_meta": {
      "title": "Video Combine 🎥🅥🅗🅢"
    }
  }
}
"""




prompt = json.loads(prompt_text)
#set the text prompt for our positive CLIPTextEncode

#提示詞設定
prompt["44"]["inputs"]["text"] = "anime style anime girl with massive fennec ears and one big fluffy tail, she has blonde hair long hair blue eyes wearing a pink sweater and a long blue skirt walking in a beautiful outdoor scenery with snow mountains in the background"

#寬高設定
prompt["45"]["inputs"]["width"] = 512
prompt["45"]["inputs"]["height"] = 512

#總張數(一秒8禎所以是32/8=4秒)
prompt["45"]["inputs"]["length"] = 120
#fps
prompt["78"]["inputs"]["frame_rate"] = 24

# 🚀 發送請求到 ComfyUI
print("🚀 發送請求到 ComfyUI...")
response = queue_prompt(prompt)

if response is None or "prompt_id" not in response:
    print("❌ API 回應錯誤，請檢查 ComfyUI 設定")
    exit()

prompt_id = response["prompt_id"]
print(f"🆔 獲取 prompt_id: {prompt_id}")

# 監聽 ComfyUI 任務進度
wait_for_completion(prompt_id)

# 取得 API 回傳的 MP4 檔案名稱並搬移
move_output_files(prompt_id)
