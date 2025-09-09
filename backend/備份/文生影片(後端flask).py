import json
import os
import shutil
import time
import uuid
import urllib.request
import websocket  # 請先安裝 websocket-client
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
    methods=["GET", "POST", "OPTIONS", "DELETE"]
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# -----------------------------
# ComfyUI 與目標資料夾設定
# -----------------------------
server_address = "127.0.0.1:8188"  # ComfyUI 伺服器位址（本機）
client_id = str(uuid.uuid4())      # 產生唯一 client ID

# ComfyUI 輸出資料夾 (影片將先產出於此)
comfyui_output_dir = "D:/comfyui/ComfyUI_windows_portable/ComfyUI/output/"
# 目標資料夾 (搬移後影片存放處)
target_dir = "D:/sd1.5_animediff_txt2video_dataset/"
os.makedirs(target_dir, exist_ok=True)

# -----------------------------
# 輔助函式
# -----------------------------
def queue_prompt(prompt):
    """發送請求到 ComfyUI /prompt API，並回傳結果"""
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())

def wait_for_completion(prompt_id):
    """透過 WebSocket 監聽 ComfyUI 任務進度，直到完成"""
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    print("🕐 等待 ComfyUI 任務完成...")
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                # 當收到 "executing" 訊息，且 prompt_id 相符且沒有指定 node 時，視為完成
                if message.get("type") == "executing":
                    data = message.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("✅ 任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")

def get_history(prompt_id):
    """從 ComfyUI /history API 取得任務輸出紀錄"""
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print(f"📜 Debug: history API 回應 = {json.dumps(history_data, indent=4)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def find_latest_mp4():
    """在 ComfyUI 輸出資料夾中尋找最新的 MP4 檔案"""
    mp4_files = [f for f in os.listdir(comfyui_output_dir) if f.endswith(".mp4")]
    if not mp4_files:
        print("🚫 找不到 MP4 檔案！")
        return None
    latest_mp4 = max(mp4_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎬 找到最新 MP4: {latest_mp4}")
    return latest_mp4

def get_final_video_filename(prompt_id):
    """從 /history API 或檔案搜尋中取得最終 MP4 檔案名稱"""
    history = get_history(prompt_id)
    if not history:
        print("⚠️ history API 回應為空，改用檔案搜尋。")
        return find_latest_mp4()
    video_node = history.get("outputs", {}).get("52", {})
    if "gifs" in video_node:
        for video in video_node["gifs"]:
            print(f"🎬 Found video from API: {video['filename']}")
            if video["filename"].endswith(".mp4"):
                return video["filename"]
    print("⚠️ API 未找到 MP4，改用檔案搜尋。")
    return find_latest_mp4()

def move_output_files(prompt_id):
    """將生成的 MP4 檔案從 ComfyUI 輸出資料夾搬移到目標資料夾"""
    mp4_filename = get_final_video_filename(prompt_id)
    if not mp4_filename:
        print("🚫 無法獲取 MP4 檔案名稱！")
        return None
    source_path = os.path.join(comfyui_output_dir, mp4_filename)
    target_path = os.path.join(target_dir, mp4_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return None
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
        return mp4_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None

# -----------------------------
# 工作流程 JSON (影片生成) - 以 animediff_1.5 為基底
# -----------------------------
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

@app.route("/generate_video", methods=["POST"])
def generate_video_endpoint():
    """
    接收前端傳來的影片生成請求，
    根據描述與參數組合工作流程 JSON，
    呼叫 ComfyUI 產生影片，
    搬移生成的 MP4 檔案，
    並回傳對外 HTTPS 影片 URL。
    """
    data = request.json
    description = data.get("text", "").strip()
    if not description:
        return jsonify({"error": "請提供有效的描述文字"}), 400

    try:
        duration = int(data.get("duration", 4))
    except ValueError:
        duration = 4
    try:
        frame_rate = int(data.get("frame_rate", 8))
    except ValueError:
        frame_rate = 8
    try:
        seed = int(data.get("seed", 103))
    except ValueError:
        seed = 103

    # 更新影片生成的工作流程參數
    try:
        prompt = json.loads(prompt_text)
    except json.JSONDecodeError as e:
        return jsonify({"error": "工作流程 JSON 格式錯誤", "details": str(e)}), 500

    # 使用翻譯後的描述作為提示詞
    prompt["88"]["inputs"]["text"] = description
    prompt["7"]["inputs"]["cfg"] = 7
    prompt["7"]["inputs"]["sampler_name"] = "euler"
    prompt["7"]["inputs"]["scheduler"] = "karras"
    prompt["9"]["inputs"]["batch_size"] = duration * frame_rate
    prompt["20"]["inputs"]["model_name"] = "mm_sd_v15.ckpt"
    prompt["54"]["inputs"]["model_name"] = "control_sd15_canny.pth"
    prompt["7"]["inputs"]["seed"] = seed

    print("🚀 發送工作流程到 ComfyUI...")
    resp_data = queue_prompt(prompt)
    if not resp_data or "prompt_id" not in resp_data:
        return jsonify({"error": "ComfyUI API 回應錯誤"}), 500

    prompt_id = resp_data["prompt_id"]
    print(f"🔹 取得 prompt_id: {prompt_id}")

    wait_for_completion(prompt_id)
    time.sleep(5)  # 視情況調整等待時間

    print("✅ 任務完成，開始搬移影片檔案...")
    mp4_filename = move_output_files(prompt_id)
    if not mp4_filename:
        return jsonify({"error": "搬移影片失敗"}), 500

    video_url = f"https://api.picturesmagician.com/get_video/{mp4_filename}?t={int(time.time())}"
    print("🔹 回傳影片 URL:", video_url)
    return jsonify({"video_url": video_url})

@app.route("/get_video/<path:filename>", methods=["GET"])
def get_video(filename):
    file_path = os.path.join(target_dir, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "檔案不存在"}), 404
    return send_from_directory(target_dir, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
