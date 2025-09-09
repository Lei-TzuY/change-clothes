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
target_dir = "D:/sd1.5_animediff_txt2video_dataset/"
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

    # 🔍 嘗試從 `VHS_VideoCombine` (`52` 節點) 查找 MP4
    video_node = history.get("outputs", {}).get("52", {})
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
  "2": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "VAE載入器"
    }
  },
  "4": {
    "inputs": {
      "stop_at_clip_layer": -1,
      "clip": [
        "22",
        1
      ]
    },
    "class_type": "CLIPSetLastLayer",
    "_meta": {
      "title": "CLIP設定停止層"
    }
  },
  "7": {
    "inputs": {
      "seed": 1079132525953378,
      "steps": 20,
      "cfg": 7,
      "sampler_name": "euler",
      "scheduler": "karras",
      "denoise": 1,
      "model": [
        "20",
        0
      ],
      "positive": [
        "88",
        0
      ],
      "negative": [
        "69",
        0
      ],
      "latent_image": [
        "9",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "K採樣器"
    }
  },
  "9": {
    "inputs": {
      "width": 512,
      "height": 512,
      "batch_size": 32
    },
    "class_type": "EmptyLatentImage",
    "_meta": {
      "title": "空Latent"
    }
  },
  "10": {
    "inputs": {
      "samples": [
        "7",
        0
      ],
      "vae": [
        "2",
        0
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE解碼"
    }
  },
  "13": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "scale_by": 1.5,
      "samples": [
        "7",
        0
      ]
    },
    "class_type": "LatentUpscaleBy",
    "_meta": {
      "title": "Latent按係數縮放"
    }
  },
  "14": {
    "inputs": {
      "seed": 1079132525953378,
      "steps": 30,
      "cfg": 6.5,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 0.6,
      "model": [
        "20",
        0
      ],
      "positive": [
        "88",
        0
      ],
      "negative": [
        "69",
        0
      ],
      "latent_image": [
        "13",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "K採樣器"
    }
  },
  "20": {
    "inputs": {
      "model_name": "mm_sd_v15.ckpt",
      "beta_schedule": "sqrt_linear (AnimateDiff)",
      "motion_scale": 1.1,
      "apply_v2_models_properly": true,
      "model": [
        "22",
        0
      ],
      "context_options": [
        "25",
        0
      ]
    },
    "class_type": "ADE_AnimateDiffLoaderWithContext",
    "_meta": {
      "title": "AnimateDiff Loader [Legacy] 🎭🅐🅓①"
    }
  },
  "22": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Checkpoint載入器(簡易)"
    }
  },
  "25": {
    "inputs": {
      "context_length": 16,
      "context_stride": 1,
      "context_overlap": 8,
      "context_schedule": "uniform",
      "closed_loop": false,
      "fuse_method": "pyramid",
      "use_on_equal_length": false,
      "start_percent": 0,
      "guarantee_steps": 1
    },
    "class_type": "ADE_AnimateDiffUniformContextOptions",
    "_meta": {
      "title": "Context Options◆Looped Uniform 🎭🅐🅓"
    }
  },
  "45": {
    "inputs": {
      "frame_rate": 8,
      "loop_count": 0,
      "filename_prefix": "txt2video_animediff_api_gen",
      "format": "video/h264-mp4",
      "pix_fmt": "yuv420p",
      "crf": 19,
      "save_metadata": true,
      "trim_to_audio": false,
      "pingpong": false,
      "save_output": true,
      "images": [
        "10",
        0
      ]
    },
    "class_type": "VHS_VideoCombine",
    "_meta": {
      "title": "Video Combine 🎥🅥🅗🅢"
    }
  },
  "46": {
    "inputs": {
      "samples": [
        "14",
        0
      ],
      "vae": [
        "2",
        0
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE解碼"
    }
  },
  "49": {
    "inputs": {
      "strength": 1,
      "start_percent": 0,
      "end_percent": 1,
      "positive": [
        "88",
        0
      ],
      "negative": [
        "69",
        0
      ],
      "control_net": [
        "54",
        0
      ],
      "image": [
        "71",
        0
      ]
    },
    "class_type": "ControlNetApplyAdvanced",
    "_meta": {
      "title": "ControlNet應用(進階)"
    }
  },
  "50": {
    "inputs": {
      "seed": 1079132525953378,
      "steps": 30,
      "cfg": 6.5,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 0.6,
      "model": [
        "20",
        0
      ],
      "positive": [
        "49",
        0
      ],
      "negative": [
        "49",
        1
      ],
      "latent_image": [
        "61",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "K採樣器"
    }
  },
  "51": {
    "inputs": {
      "samples": [
        "50",
        0
      ],
      "vae": [
        "2",
        0
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE解碼"
    }
  },
  "52": {
    "inputs": {
      "frame_rate": 8,
      "loop_count": 0,
      "filename_prefix": "txt2video_animediff_api_gen",
      "format": "video/h264-mp4",
      "pix_fmt": "yuv420p",
      "crf": 19,
      "save_metadata": true,
      "trim_to_audio": false,
      "pingpong": false,
      "save_output": true,
      "images": [
        "51",
        0
      ]
    },
    "class_type": "VHS_VideoCombine",
    "_meta": {
      "title": "Video Combine 🎥🅥🅗🅢"
    }
  },
  "54": {
    "inputs": {
      "control_net_name": "control_sd15_canny.pth",
      "tk_optional": [
        "56",
        1
      ]
    },
    "class_type": "ControlNetLoaderAdvanced",
    "_meta": {
      "title": "ControlNet載入器(進階)"
    }
  },
  "56": {
    "inputs": {
      "base_multiplier": 0.825,
      "flip_weights": false,
      "uncond_multiplier": 1
    },
    "class_type": "ScaledSoftControlNetWeights",
    "_meta": {
      "title": "縮放柔和ControlNet權重"
    }
  },
  "61": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "scale_by": 1.5,
      "samples": [
        "7",
        0
      ]
    },
    "class_type": "LatentUpscaleBy",
    "_meta": {
      "title": "Latent按係數縮放"
    }
  },
  "69": {
    "inputs": {
      "text": "(low quality, nsfw, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
      "clip": [
        "4",
        0
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "71": {
    "inputs": {
      "resolution": 512,
      "image": [
        "46",
        0
      ]
    },
    "class_type": "AnimeLineArtPreprocessor",
    "_meta": {
      "title": "AnimeLineArt動漫線稿預處理器"
    }
  },
  "88": {
    "inputs": {
      "text": "a girl dance",
      "clip": [
        "4",
        0
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  }
}
"""




prompt = json.loads(prompt_text)
#set the text prompt for our positive CLIPTextEncode
#vae設定
prompt["2"]["inputs"]["vae_name"] = "kl-f8-anime2.safetensors"
#checkpoint設定
prompt["22"]["inputs"]["ckpt_name"] = "meinamix_v12Final.safetensors"
#提示詞設定
prompt["88"]["inputs"]["text"] = "a girl dance"
#cfg設定(提示詞相關性)
prompt["7"]["inputs"]["cfg"] = 7
#採樣器設定
prompt["7"]["inputs"]["sampler_name"] = "euler"
#排程設定
prompt["7"]["inputs"]["scheduler"] = "karras"
#總張數(一秒8禎所以是32/8=4秒)
prompt["9"]["inputs"]["batch_size"] = 32
#使用的影片模型
prompt["20"]["inputs"]["model_name"] = "mm_sd_v15.ckpt"
#控制網路模型
prompt["54"]["inputs"]["model_name"] = "control_sd15_canny.pth"
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
