import json
import os
import shutil
import websocket  # 確保安裝 `websocket-client` 模組
import urllib.request
import urllib.error
import urllib.parse
import uuid
import random

# ----------------------------------------------------------------------------
# ComfyUI 伺服器位址
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())  # 產生唯一 client ID

# ComfyUI 輸出與目標資料夾
comfyui_output_dir = "D:/comfyui/ComfyUI_windows_portable/ComfyUI/output/"
target_dir = "D:/sd1.5_lora_animediff_video2video_dataset/"
os.makedirs(comfyui_output_dir, exist_ok=True)  # 確保輸出資料夾存在
os.makedirs(target_dir, exist_ok=True)  # 確保目標資料夾存在
# ----------------------------------------------------------------------------


def queue_prompt(prompt):
    """發送請求到 ComfyUI API"""
    p = {
        "prompt": prompt,
        "client_id": client_id,
        "disable_cached_nodes": True  # 強制禁用快取
    }
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(
        f"http://{server_address}/prompt",
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP 錯誤: {e.code} {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"❌ URL 錯誤: {e.reason}")
        return None


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
                if message.get("type") == "executing":
                    data = message.get("data", {})
                    # 當 node=None 且 prompt_id 對應時代表流程已結束
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")


def get_history_all():
    """
    獲取 /history 全部資料（回傳一個 Dict: { prompt_id: {...}, prompt_id2: {...}, ... }）
    也可用來檢查 ComfyUI 是否有正確維護歷史。
    """
    url = f"http://{server_address}/history"
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())
    except Exception as e:
        print(f"❌ 無法取得完整 /history: {e}")
        return {}


def get_history(prompt_id):
    """從 /history/{prompt_id} 取得特定任務的詳細歷史"""
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as response:
            history_data = json.loads(response.read())
        print(f"📜 Debug: history API 回應 = {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP 錯誤: {e.code} {e.reason}")
        return {}
    except urllib.error.URLError as e:
        print(f"❌ URL 錯誤: {e.reason}")
        return {}
    except Exception as e:
        print(f"❌ 其他錯誤: {e}")
        return {}


def check_history(prompt_id, node_id="102"):
    """
    偵錯用：列出指定 prompt_id 的完整 /history 資料，
    並嘗試找出在 node_id 下的「videos」或「files」中是否有 .mp4 檔案。
    """
    history = get_history(prompt_id)
    if not history:
        print(f"⚠️ 無法取得 prompt_id = {prompt_id} 的任何資料。")
        return

    # 查看對應 node 輸出
    node_data = history.get("outputs", {}).get(node_id, {})
    if not node_data:
        print(f"⚠️ node {node_id} 在這個 prompt_id 中沒有任何輸出。")
        return

    # 1) videos
    if "videos" in node_data:
        for vid in node_data["videos"]:
            filename = vid.get("filename", "")
            if filename.endswith(".mp4"):
                print(f"🎬 在 node {node_id} -> videos 找到 MP4: {filename}")
    else:
        print(f"⚠️ node {node_id} 下沒有 'videos' 欄位。")

    # 2) files
    if "files" in node_data:
        for f in node_data["files"]:
            filename = f.get("filename", "")
            if filename.endswith(".mp4"):
                print(f"🎬 在 node {node_id} -> files 找到 MP4: {filename}")
    else:
        print(f"⚠️ node {node_id} 下沒有 'files' 欄位。")


def find_latest_mp4():
    """從 ComfyUI 輸出資料夾尋找最新的 MP4 檔案"""
    mp4_files = [f for f in os.listdir(comfyui_output_dir) if f.endswith(".mp4")]
    if not mp4_files:
        print("🚫 找不到 MP4 檔案！")
        return None
    latest_mp4 = max(mp4_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎬 找到最新 MP4: {latest_mp4}")
    return latest_mp4


def get_final_video_filename(prompt_id):
    """取得 VHS_VideoCombine 產出的 MP4 檔案名稱（從 /history 先查 videos/files/gifs，找不到就用檔案搜尋）"""
    history = get_history(prompt_id)
    if not history:
        print("⚠️ API 沒回傳任何資訊，改用檔案搜尋。")
        return find_latest_mp4()

    # 假設 node ID 為 102
    video_node = history.get("outputs", {}).get("102", {})

    # 1) videos
    if "videos" in video_node:
        for vid in video_node["videos"]:
            filename = vid.get("filename", "")
            if filename.endswith(".mp4"):
                return filename

    # 2) files
    if "files" in video_node:
        for f in video_node["files"]:
            filename = f.get("filename", "")
            if filename.endswith(".mp4"):
                return filename

    # 3) gifs
    if "gifs" in video_node:
        for g in video_node["gifs"]:
            filename = g.get("filename", "")
            if filename.endswith(".mp4"):
                return filename

    # 如果都找不到 .mp4，就改用檔案搜尋
    print("⚠️ API 沒找到 MP4，改用檔案搜尋。")
    return find_latest_mp4()


def move_output_files(prompt_id):
    """搬移 get_final_video_filename() 找到的 MP4 檔案"""
    mp4_filename = get_final_video_filename(prompt_id)

    if not mp4_filename:
        print("🚫 無法從 API 或檔案搜尋獲取 MP4 檔案名稱！")
        return

    source_path = os.path.join(comfyui_output_dir, mp4_filename)
    target_path = os.path.join(target_dir, mp4_filename)

    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return

    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")


# ----------------------------------------------------------------------------
# 以下為你指定「要保留」的各種參數設定區塊：
# ----------------------------------------------------------------------------

# ComfyUI API JSON Prompt
prompt = {
  "1": {
    "inputs": {
      "ckpt_name": "meinamix_v12Final.safetensors",
      "beta_schedule": "sqrt_linear (AnimateDiff)",
      "use_custom_scale_factor": False,
      "scale_factor": 0.18215
    },
    "class_type": "CheckpointLoaderSimpleWithNoiseSelect",
    "_meta": {
      "title": "Load Checkpoint w/ Noise Select 🎭🅐🅓"
    }
  },
  "2": {
    "inputs": {
      "vae_name": "kl-f8-anime2.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {
      "title": "VAE載入器"
    }
  },
  "6": {
    "inputs": {
      "text": "(low quality, nsfw, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly",
      "clip": [
        "111",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP文本編碼器"
    }
  },
  "7": {
    "inputs": {
      "seed": 148741830304879,
      "steps": 25,
      "cfg": 7,
      "sampler_name": "euler_ancestral",
      "scheduler": "normal",
      "denoise": 1,
      "model": [
        "93",
        0
      ],
      "positive": [
        "72",
        0
      ],
      "negative": [
        "72",
        1
      ],
      "latent_image": [
        "56",
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
  "12": {
    "inputs": {
      "filename_prefix": "Images\\image",
      "images": [
        "10",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "儲存圖像"
    }
  },
  "50": {
    "inputs": {
      "images": [
        "53",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "53": {
    "inputs": {
      "upscale_method": "nearest-exact",
      "width": 1024,
      "height": 576,
      "crop": "disabled",
      "image": [
        "109",
        0
      ]
    },
    "class_type": "ImageScale",
    "_meta": {
      "title": "圖像縮放"
    }
  },
  "56": {
    "inputs": {
      "pixels": [
        "53",
        0
      ],
      "vae": [
        "2",
        0
      ]
    },
    "class_type": "VAEEncode",
    "_meta": {
      "title": "VAE編碼"
    }
  },
  "70": {
    "inputs": {
      "control_net_name": "sd1.5_lineart.safetensors"
    },
    "class_type": "ControlNetLoaderAdvanced",
    "_meta": {
      "title": "ControlNet載入器(進階)"
    }
  },
  "71": {
    "inputs": {
      "coarse": "disable",
      "resolution": 512,
      "image": [
        "53",
        0
      ]
    },
    "class_type": "LineArtPreprocessor",
    "_meta": {
      "title": "LineArt線稿預處理"
    }
  },
  "72": {
    "inputs": {
      "strength": 0.5,
      "start_percent": 0.018000000000000002,
      "end_percent": 1,
      "positive": [
        "96",
        0
      ],
      "negative": [
        "6",
        0
      ],
      "control_net": [
        "70",
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
  "92": {
    "inputs": {
      "images": [
        "71",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  },
  "93": {
    "inputs": {
      "model_name": "mm_sd_v15.ckpt",
      "beta_schedule": "sqrt_linear (AnimateDiff)",
      "motion_scale": 1,
      "apply_v2_models_properly": True,
      "model": [
        "111",
        0
      ],
      "context_options": [
        "94",
        0
      ]
    },
    "class_type": "ADE_AnimateDiffLoaderWithContext",
    "_meta": {
      "title": "AnimateDiff Loader [Legacy] 🎭🅐🅓①"
    }
  },
  "94": {
    "inputs": {
      "context_length": 16,
      "context_stride": 1,
      "context_overlap": 4,
      "context_schedule": "uniform",
      "closed_loop": False,
      "fuse_method": "flat",
      "use_on_equal_length": False,
      "start_percent": 0,
      "guarantee_steps": 1
    },
    "class_type": "ADE_AnimateDiffUniformContextOptions",
    "_meta": {
      "title": "Context Options◆Looped Uniform 🎭🅐🅓"
    }
  },
  "96": {
    "inputs": {
      "text": "\"0\" :\"spring day, cherryblossoms\",\n\"8\" :\"summer day, vegetation\",\n\"16\" :\"fall day, leaves blowing in the wind\",\n\"32\" :\"winter, during a snowstorm, earmuffs\"\n",
      "max_frames": 120,
      "print_output": "",
      "pre_text": [
        "101",
        0
      ],
      "start_frame": 0,
      "end_frame": 0,
      "clip": [
        "111",
        1
      ]
    },
    "class_type": "BatchPromptSchedule",
    "_meta": {
      "title": "Batch Prompt Schedule 📅🅕🅝"
    }
  },
  "101": {
    "inputs": {
      "text": "(Masterpiece, best quality:1.2), closeup, a guy walking through forest "
    },
    "class_type": "ttN text",
    "_meta": {
      "title": "text"
    }
  },
  "102": {
    "inputs": {
      "frame_rate": 8,
      "loop_count": 0,
      "filename_prefix": "AnimateDiff",
      "format": "video/h265-mp4",
      "pix_fmt": "yuv420p10le",
      "crf": 22,
      "save_metadata": True,
      "pingpong": False,
      "save_output": True,
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
  "109": {
    "inputs": {
      "video": "\"D:\\sd1.5_animediff_txt2video_dataset\\1031_1_00003.mp4\"",
      "force_rate": 0,
      "force_size": "Disabled",
      "custom_width": 512,
      "custom_height": 512,
      "frame_load_cap": 120,
      "skip_first_frames": 0,
      "select_every_nth": 1
    },
    "class_type": "VHS_LoadVideoPath",
    "_meta": {
      "title": "Load Video (Path) 🎥🅥🅗🅢"
    }
  },
  "111": {
    "inputs": {
      "lora_name": "super-vanilla-newlora-ver1-p.safetensors",
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
  }
}
# ----------------------------------------------------------------------------
# 以下為你「另外」指定並保留的參數設置
# ----------------------------------------------------------------------------

# VAE 設定
prompt["2"]["inputs"]["vae_name"] = "kl-f8-anime2.safetensors"

# Checkpoint 設定
prompt["1"]["inputs"]["ckpt_name"] = "meinamix_v12Final.safetensors"
# lora設定
prompt["111"]["inputs"]["lora_name"] = "super-vanilla-newlora-ver1-p.safetensors"
prompt["111"]["inputs"]["strength_model"] = 1
prompt["111"]["inputs"]["strength_clip"] = 1

# 提示詞前綴設定
prompt["101"]["inputs"]["text"] = "(Masterpiece, best quality:1.2),vanilla"

# 提示詞每禎設定
animation_prompts = {
    "0": "spring day, cherryblossoms",
    "8": "summer day, vegetation",
    "16": "fall day, leaves blowing in the wind",
    "32": "winter, during a snowstorm, earmuffs"
}
text_field = ",\n".join([f'"{k}" :"{v}"' for k, v in animation_prompts.items()])
prompt["96"]["inputs"]["text"] = text_field

# 短影片上傳設定
prompt["109"]["inputs"]["video"] = r"D:\sd1.5_animediff_video2video_dataset\AnimateDiff_00003.mp4"

# 長寬設定
prompt["53"]["inputs"]["width"] = 512
prompt["53"]["inputs"]["height"] = 512

# CFG 值（提示詞遵從度）
prompt["7"]["inputs"]["cfg"] = 7
# 隨機種子
prompt["7"]["inputs"]["seed"] = random.randint(0, 999999999)

# 上傳影片最大禎數設定（需與以下一致）
prompt["109"]["inputs"]["frame_load_cap"] = 120
prompt["96"]["inputs"]["max_frames"] = 120

# 一秒多少禎
prompt["94"]["inputs"]["context_length"] = 16
#線條控制網路
prompt["70"]["inputs"]["control_net_name"] = "sd1.5_lineart.safetensors"
#動畫模型
prompt["93"]["inputs"]["model_name"] = "mm_sd_v15.ckpt"

# ----------------------------------------------------------------------------
# 程式入口：發送 prompt → 等待 → 搬移檔案
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    print("🚀 發送請求到 ComfyUI...")
    try:
        response = queue_prompt(prompt)
    except Exception as e:
        print(f"❌ 發送請求失敗: {e}")
        exit()

    if response is None or "prompt_id" not in response:
        print("❌ API 回應錯誤，請檢查 ComfyUI 設定")
        exit()

    prompt_id = response["prompt_id"]
    print(f"🆔 獲取 prompt_id: {prompt_id}")

    # 監聽 ComfyUI 任務進度
    wait_for_completion(prompt_id)

    # (選擇性) 偵錯 /history：
    # check_history(prompt_id, node_id="102")  # 如果需要看更詳細資訊可以呼叫這行

    # 取得 API 回傳的 MP4 檔案名稱並搬移
    move_output_files(prompt_id)
