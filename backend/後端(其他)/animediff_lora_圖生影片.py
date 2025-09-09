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
target_dir = "D:/sd1.5_animediff_lora_img2video_dataset/"
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

    # 🔍 嘗試從 `VHS_VideoCombine` (`261` 節點) 查找 MP4
    video_node = history.get("outputs", {}).get("261", {})
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
prompt_text ="""
{
  "61": {
    "inputs": {
      "text": "a white hair girl walking",
      "clip": [
        "199",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "183": {
    "inputs": {
      "multiply_by": 64,
      "latents": [
        "270",
        0
      ]
    },
    "class_type": "VHS_DuplicateLatents",
    "_meta": {
      "title": "Repeat Latents 🎥🅥🅗🅢"
    }
  },
  "186": {
    "inputs": {
      "model_name": "mm_sd_v15.ckpt",
      "beta_schedule": "sqrt_linear (AnimateDiff)",
      "motion_scale": 1,
      "apply_v2_models_properly": true,
      "model": [
        "314",
        0
      ],
      "context_options": [
        "197",
        0
      ]
    },
    "class_type": "ADE_AnimateDiffLoaderWithContext",
    "_meta": {
      "title": "AnimateDiff Loader [Legacy] 🎭🅐🅓①"
    }
  },
  "197": {
    "inputs": {
      "context_length": 16,
      "context_stride": 2,
      "context_overlap": 4,
      "context_schedule": "uniform",
      "closed_loop": false,
      "fuse_method": "flat",
      "use_on_equal_length": false,
      "start_percent": 0,
      "guarantee_steps": 1
    },
    "class_type": "ADE_AnimateDiffUniformContextOptions",
    "_meta": {
      "title": "Context Options◆Looped Uniform 🎭🅐🅓"
    }
  },
  "199": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Checkpoint載入器(簡易)"
    }
  },
  "261": {
    "inputs": {
      "frame_rate": 8,
      "loop_count": 0,
      "filename_prefix": "AnimateDiff",
      "format": "video/h264-mp4",
      "pix_fmt": "yuv420p",
      "crf": 19,
      "save_metadata": true,
      "trim_to_audio": false,
      "pingpong": false,
      "save_output": true,
      "images": [
        "281",
        5
      ]
    },
    "class_type": "VHS_VideoCombine",
    "_meta": {
      "title": "Video Combine 🎥🅥🅗🅢"
    }
  },
  "267": {
    "inputs": {
      "stop_at_clip_layer": -14,
      "clip": [
        "199",
        1
      ]
    },
    "class_type": "CLIPSetLastLayer",
    "_meta": {
      "title": "CLIP設定停止層"
    }
  },
  "269": {
    "inputs": {
      "pixels": [
        "340",
        0
      ],
      "vae": [
        "338",
        0
      ]
    },
    "class_type": "VAEEncode",
    "_meta": {
      "title": "VAE編碼"
    }
  },
  "270": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 512,
      "height": 768,
      "crop": "disabled",
      "samples": [
        "269",
        0
      ]
    },
    "class_type": "LatentUpscale",
    "_meta": {
      "title": "Latent縮放"
    }
  },
  "271": {
    "inputs": {
      "model_name": "mm_sd_v15.ckpt",
      "beta_schedule": "sqrt_linear (AnimateDiff)",
      "motion_scale": 1,
      "apply_v2_models_properly": true,
      "model": [
        "314",
        0
      ],
      "context_options": [
        "197",
        0
      ]
    },
    "class_type": "ADE_AnimateDiffLoaderWithContext",
    "_meta": {
      "title": "AnimateDiff Loader [Legacy] 🎭🅐🅓①"
    }
  },
  "277": {
    "inputs": {
      "seed": 217460870924708,
      "steps": 20,
      "cfg": 12,
      "sampler_name": "euler",
      "scheduler": "karras",
      "denoise": 1,
      "preview_method": "auto",
      "vae_decode": "true",
      "model": [
        "271",
        0
      ],
      "positive": [
        "279",
        1
      ],
      "negative": [
        "279",
        2
      ],
      "latent_image": [
        "279",
        3
      ],
      "optional_vae": [
        "279",
        4
      ]
    },
    "class_type": "KSampler (Efficient)",
    "_meta": {
      "title": "K採樣器(效率)"
    }
  },
  "278": {
    "inputs": {
      "seed": 453587441579143,
      "steps": 20,
      "cfg": 12,
      "sampler_name": "euler",
      "scheduler": "karras",
      "denoise": 1,
      "preview_method": "auto",
      "vae_decode": "true",
      "model": [
        "277",
        0
      ],
      "positive": [
        "277",
        1
      ],
      "negative": [
        "277",
        2
      ],
      "latent_image": [
        "277",
        3
      ],
      "optional_vae": [
        "277",
        4
      ]
    },
    "class_type": "KSampler (Efficient)",
    "_meta": {
      "title": "K採樣器(效率)"
    }
  },
  "279": {
    "inputs": {
      "seed": 689898909542969,
      "steps": 20,
      "cfg": 25,
      "sampler_name": "euler",
      "scheduler": "karras",
      "denoise": 1,
      "preview_method": "auto",
      "vae_decode": "true",
      "model": [
        "186",
        0
      ],
      "positive": [
        "61",
        0
      ],
      "negative": [
        "336",
        0
      ],
      "latent_image": [
        "289",
        0
      ],
      "optional_vae": [
        "338",
        0
      ]
    },
    "class_type": "KSampler (Efficient)",
    "_meta": {
      "title": "K採樣器(效率)"
    }
  },
  "281": {
    "inputs": {
      "seed": 744353399792849,
      "steps": 20,
      "cfg": 12,
      "sampler_name": "euler",
      "scheduler": "karras",
      "denoise": 1,
      "preview_method": "auto",
      "vae_decode": "true",
      "model": [
        "278",
        0
      ],
      "positive": [
        "278",
        1
      ],
      "negative": [
        "278",
        2
      ],
      "latent_image": [
        "334",
        0
      ],
      "optional_vae": [
        "278",
        4
      ]
    },
    "class_type": "KSampler (Efficient)",
    "_meta": {
      "title": "K採樣器(效率)"
    }
  },
  "289": {
    "inputs": {
      "boolean": false,
      "latent_a": [
        "183",
        0
      ],
      "latent_b": [
        "291",
        0
      ]
    },
    "class_type": "Latent Input Switch",
    "_meta": {
      "title": "Latent切換"
    }
  },
  "291": {
    "inputs": {
      "width": 512,
      "height": 768,
      "batch_size": 64
    },
    "class_type": "ADE_EmptyLatentImageLarge",
    "_meta": {
      "title": "Empty Latent Image (Big Batch) 🎭🅐🅓"
    }
  },
  "314": {
    "inputs": {
      "lora_name": "sj.safetensors",
      "strength_model": 0.55,
      "strength_clip": 1,
      "model": [
        "199",
        0
      ],
      "clip": [
        "199",
        1
      ]
    },
    "class_type": "LoraLoader",
    "_meta": {
      "title": "LoRA載入器"
    }
  },
  "333": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "scale_by": 1.25,
      "image": [
        "278",
        5
      ]
    },
    "class_type": "ImageScaleBy",
    "_meta": {
      "title": "圖像按係數縮放"
    }
  },
  "334": {
    "inputs": {
      "tile_size": 512,
      "overlap": 64,
      "temporal_size": 64,
      "temporal_overlap": 8,
      "pixels": [
        "333",
        0
      ],
      "vae": [
        "278",
        4
      ]
    },
    "class_type": "VAEEncodeTiled",
    "_meta": {
      "title": "VAE分塊編碼"
    }
  },
  "336": {
    "inputs": {
      "text": "(low quality, nsfw, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
      "clip": [
        "267",
        0
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "338": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "VAE載入器"
    }
  },
  "340": {
    "inputs": {
      "image_path": "./ComfyUI/input/example.png",
      "RGBA": "false",
      "filename_text_extension": "true"
    },
    "class_type": "Image Load",
    "_meta": {
      "title": "圖像載入"
    }
  }
}
"""

prompt = json.loads(prompt_text)
#set the text prompt for our positive CLIPTextEncode
#vae設定
prompt["338"]["inputs"]["vae_name"] = "kl-f8-anime2.safetensors"
#checkpoint設定
prompt["199"]["inputs"]["ckpt_name"] = "meinamix_v12Final.safetensors"
#lora設定
prompt["199"]["inputs"]["lora_name"] = "sj.safetensors"
prompt["199"]["inputs"]["strength_model"] = 0.55
prompt["199"]["inputs"]["strength_clip"] = 1

#提示詞設定
prompt["61"]["inputs"]["image_path"] = "a girl walking"
#圖像上傳
prompt["340"]["inputs"]["image"] =r"C:\Users\User\Desktop\雷姆.png"
#總張數(一秒16禎所以是64/16=4秒)
prompt["183"]["inputs"]["multiply_by"] = 64

#動畫模型
prompt["186"]["inputs"]["model_name"] = "mm_sd_v15.ckpt"
prompt["271"]["inputs"]["model_name"] = "mm_sd_v15.ckpt"

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
