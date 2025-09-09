import json
import os
import shutil
import websocket  # 確保安裝 `websocket-client` 模組
import urllib.request
import urllib.error
import urllib.parse
import uuid
import random
import time
import requests
import threading

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

# ----------------------------------------------------------------------------
# ComfyUI 伺服器位址與目標資料夾設定
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())  # 產生唯一 client ID

# ComfyUI 輸出與目標資料夾（請確保這些資料夾存在）
comfyui_output_dir = "D:/comfyui/ComfyUI_windows_portable/ComfyUI/output/"
target_dir = "D:/sd1.5_animediff_txt2video_dataset/"
os.makedirs(comfyui_output_dir, exist_ok=True)
os.makedirs(target_dir, exist_ok=True)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
     methods=["GET", "POST", "OPTIONS", "DELETE"])

# 讓 Flask 正確處理反向代理（例如 Cloudflare Tunnel）
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ----------------------------------------------------------------------------
# 對外提供的 HTTPS 網域設定（前端用於組合最終影片 URL）
VIDEO_BASE_URL = "https://api.picturesmagician.com"

# ----------------------------------------------------------------------------
# 以下為原始腳本中的函式定義
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
    獲取 /history 全部資料（回傳一個 Dict: { prompt_id: {...}, ... }）
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
    """取得 VHS_VideoCombine 產出的 MP4 檔案名稱（先查 /history，再用檔案搜尋）"""
    history = get_history(prompt_id)
    if not history:
        print("⚠️ API 沒回傳任何資訊，改用檔案搜尋。")
        return find_latest_mp4()
    video_node = history.get("outputs", {}).get("102", {})
    if "videos" in video_node:
        for vid in video_node["videos"]:
            filename = vid.get("filename", "")
            if filename.endswith(".mp4"):
                return filename
    if "files" in video_node:
        for f in video_node["files"]:
            filename = f.get("filename", "")
            if filename.endswith(".mp4"):
                return filename
    if "gifs" in video_node:
        for g in video_node["gifs"]:
            filename = g.get("filename", "")
            if filename.endswith(".mp4"):
                return filename
    print("⚠️ API 沒找到 MP4，改用檔案搜尋。")
    return find_latest_mp4()

def move_output_files(prompt_id):
    """搬移 get_final_video_filename() 找到的 MP4 檔案"""
    mp4_filename = get_final_video_filename(prompt_id)
    if not mp4_filename:
        print("🚫 無法從 API 或檔案搜尋獲取 MP4 檔案名稱！")
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

# ----------------------------------------------------------------------------
# 以下為參數設定區塊（請勿隨意修改）
# ----------------------------------------------------------------------------

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
            "text": "(low quality, nsfw, worst quality, text, letterboxed:1.4), (deformed, distorted, disfigured:1.3), easynegative, hands, bad-hands-5, blurry, ugly, embedding:easynegative",
            "clip": ["1", 1]
        },
        "class_type": "CLIPTextEncode",
        "_meta": {
            "title": "CLIP文本編碼器"
        }
    },
    "7": {
        "inputs": {
            "seed": 44444444,
            "steps": 25,
            "cfg": 7,
            "sampler_name": "euler_ancestral",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["93", 0],
            "positive": ["72", 0],
            "negative": ["72", 1],
            "latent_image": ["56", 0]
        },
        "class_type": "KSampler",
        "_meta": {
            "title": "K採樣器"
        }
    },
    "10": {
        "inputs": {
            "samples": ["7", 0],
            "vae": ["2", 0]
        },
        "class_type": "VAEDecode",
        "_meta": {
            "title": "VAE解碼"
        }
    },
    "12": {
        "inputs": {
            "filename_prefix": "Images\\image",
            "images": ["10", 0]
        },
        "class_type": "SaveImage",
        "_meta": {
            "title": "儲存圖像"
        }
    },
    "50": {
        "inputs": {
            "images": ["53", 0]
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
            "image": ["109", 0]
        },
        "class_type": "ImageScale",
        "_meta": {
            "title": "圖像縮放"
        }
    },
    "56": {
        "inputs": {
            "pixels": ["53", 0],
            "vae": ["2", 0]
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
            "image": ["53", 0]
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
            "positive": ["96", 0],
            "negative": ["6", 0],
            "control_net": ["70", 0],
            "image": ["71", 0]
        },
        "class_type": "ControlNetApplyAdvanced",
        "_meta": {
            "title": "ControlNet應用(進階)"
        }
    },
    "92": {
        "inputs": {
            "images": ["71", 0]
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
            "model": ["1", 0],
            "context_options": ["94", 0]
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
            "pre_text": ["101", 0],
            "app_text": "",
            "start_frame": 0,
            "end_frame": 0,
            "pw_a": 0,
            "pw_b": 0,
            "pw_c": 0,
            "pw_d": 0,
            "clip": ["1", 1]
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
            # 修改這裡：將影片格式從 H265 調整為 H264，並將像素格式改為 yuv420p
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
            "crf": 22,
            "save_metadata": True,
            "pingpong": False,
            "save_output": True,
            "images": ["10", 0]
        },
        "class_type": "VHS_VideoCombine",
        "_meta": {
            "title": "Video Combine 🎥🅥🅗🅢"
        }
    },
    "109": {
        "inputs": {
            "video": "",
            # 修改這裡：將 force_rate 從 0 改為 8，確保輸入影片幀率正確讀取
            "force_rate": 8,
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
    }
}

# ----------------------------------------------------------------------------
# Flask 路由：/generate_video2video
# ----------------------------------------------------------------------------
@app.route("/generate_video2video", methods=["POST"])
def generate_video2video():
    print("🚀 發送請求到 ComfyUI...")

    # 取得表單參數
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "請提供有效的提示詞"}), 400

    try:
        seed = int(request.form.get("seed", 0))
    except ValueError:
        seed = 0
    if seed == 0:
        seed = int(time.time() * 1000) % 1000000

    # 取得上傳的影片檔案
    video_file = request.files.get("video")
    if not video_file:
        return jsonify({"error": "請上傳影片"}), 400

    # 將上傳的影片暫存於 temp_uploads 資料夾
    temp_path = os.path.join(os.getcwd(), "temp_uploads")
    os.makedirs(temp_path, exist_ok=True)
    temp_filename = secure_filename(f"{uuid.uuid4().hex}.mp4")
    file_path = os.path.join(temp_path, temp_filename)
    video_file.save(file_path)
    print(f"✅ [後端] 接收到上傳影片並儲存於 {file_path}")

    # 更新 prompt 的短影片路徑
    prompt["109"]["inputs"]["video"] = file_path

    result = {}

    def call_comfyui():
        try:
            response = queue_prompt(prompt)
            if response is None or "prompt_id" not in response:
                result["error"] = "API 回應錯誤，請檢查 ComfyUI 設定"
                return
            prompt_id = response["prompt_id"]
            print(f"🆔 獲取 prompt_id: {prompt_id}")

            wait_for_completion(prompt_id)
            time.sleep(2)
            move_output_files(prompt_id)
            final_video_url = f"{VIDEO_BASE_URL}/get_video/{get_final_video_filename(prompt_id)}?t={int(time.time())}"
            print("影片生成成功，URL =", final_video_url)
            result["video_url"] = final_video_url
        except Exception as e:
            result["error"] = str(e)
    
    thread = threading.Thread(target=call_comfyui)
    thread.start()

    def sse_stream():
        progress = 0
        while thread.is_alive():
            msg = {"progress": progress, "message": "影片生成中..."}
            yield f"data: {json.dumps(msg)}\n\n"
            time.sleep(5)
            progress = min(progress + 10, 90)
        thread.join()
        if "video_url" in result:
            final_msg = {"progress": 100, "video_url": result["video_url"], "message": "影片生成完成！"}
            yield f"data: {json.dumps(final_msg)}\n\n"
        else:
            err = result.get("error", "未知錯誤")
            fail_msg = {"progress": 100, "error": err, "message": "影片生成失敗"}
            yield f"data: {json.dumps(fail_msg)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Access-Control-Allow-Origin": "*"
    }
    return Response(sse_stream(), headers=headers, mimetype="text/event-stream")

# ----------------------------------------------------------------------------
# GET /get_video 路由：提供影片檔案
# ----------------------------------------------------------------------------
@app.route("/get_video/<path:filename>", methods=["GET"])
def get_video(filename):
    upload_dir = os.path.join(os.getcwd(), "uploaded_videos")
    file_path1 = os.path.join(upload_dir, filename)
    file_path2 = os.path.join(target_dir, filename)
    print("檢查檔案路徑：", file_path1, "或", file_path2)
    if os.path.exists(file_path1):
        response = send_from_directory(upload_dir, filename)
    elif os.path.exists(file_path2):
        response = send_from_directory(target_dir, filename)
    else:
        return jsonify({"error": "檔案不存在", "paths": [file_path1, file_path2]}), 404
    response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
