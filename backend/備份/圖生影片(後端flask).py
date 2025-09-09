import json
import os
import shutil
import time
import uuid
import urllib.request
import urllib.error
import websocket  # 請確保 pip install websocket-client
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
import threading
from collections import OrderedDict

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
    methods=["GET", "POST", "OPTIONS", "DELETE"]
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ------------------------------------------------------
# ComfyUI 伺服器位址（本機）
# ------------------------------------------------------
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())

# ------------------------------------------------------
# 資料夾設定
# ------------------------------------------------------
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
target_dir = r"D:\sd1.5_animediff_img2video_dataset"
os.makedirs(target_dir, exist_ok=True)

# ------------------------------------------------------
# 輔助函式
# ------------------------------------------------------
def queue_prompt(prompt):
    """
    發送 ComfyUI API 請求 (/prompt)，回傳 JSON 結果
    """
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def wait_for_completion(prompt_id):
    """
    透過 WebSocket 監聽 ComfyUI 任務進度，直到完成
    """
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    print("等待 ComfyUI 任務完成...")
    try:
        ws = websocket.create_connection(ws_url)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                msg = json.loads(out)
                if msg.get("type") == "executing":
                    data = msg.get("data", {})
                    # 當 node 為 None，且 prompt_id 相符，表示任務完成
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        print("任務已完成！")
                        break
        ws.close()
    except Exception as e:
        print(f"WebSocket 連線錯誤: {e}")

def get_history(prompt_id):
    """
    從 ComfyUI /history/{prompt_id} 取得輸出紀錄
    """
    url = f"http://{server_address}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            history_data = json.loads(resp.read())
        print("[Debug] history API 回應:", json.dumps(history_data, indent=4))
        return history_data.get(prompt_id, {})
    except Exception as e:
        print("無法取得歷史紀錄:", e)
        return {}

def find_latest_mp4():
    """
    在 comfyui_output_dir 中尋找最新的 MP4 檔案
    """
    mp4_files = [f for f in os.listdir(comfyui_output_dir) if f.endswith(".mp4")]
    if not mp4_files:
        print("找不到 MP4 檔案！")
        return None
    latest_mp4 = max(mp4_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print("找到最新 MP4:", latest_mp4)
    return latest_mp4

def get_final_video_filename(prompt_id):
    """
    解析 /history 或 fallback 到檔案搜尋，找出最終生成的 MP4 檔名
    """
    history = get_history(prompt_id)
    if not history:
        print("history API 回應為空，改用檔案搜尋。")
        return find_latest_mp4()

    # 依照工作流程中 "video combine" 節點 ID 做調整，這裡假設是 "261"
    node_261 = history.get("outputs", {}).get("261", {})
    if "gifs" in node_261:
        for video_item in node_261["gifs"]:
            filename = video_item.get("filename", "")
            if filename.endswith(".mp4"):
                print("API 回傳 MP4 檔案:", filename)
                return filename

    print("API 未找到 MP4，改用檔案搜尋。")
    return find_latest_mp4()

def move_output_files(prompt_id):
    """
    搬移最終 MP4 檔案到 target_dir
    """
    mp4_filename = get_final_video_filename(prompt_id)
    if not mp4_filename:
        print("無法獲取 MP4 檔案名稱！")
        return None
    source_path = os.path.join(comfyui_output_dir, mp4_filename)
    target_path = os.path.join(target_dir, mp4_filename)
    if not os.path.exists(source_path):
        print(f"找不到 {source_path}，無法搬移！")
        return None
    try:
        shutil.move(source_path, target_path)
        print(f"已搬移: {source_path} → {target_path}")
        return mp4_filename
    except Exception as e:
        print("搬移失敗:", e)
        return None

# ------------------------------------------------------
# 範例工作流程 (請根據實際需求修改 animediff+LoRA 內容)
# ------------------------------------------------------
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

# ------------------------------------------------------
# /generate_img2video：接收前端的 multipart/form-data
# ------------------------------------------------------
@app.route("/generate_img2video", methods=["POST"])
def generate_img2video():
    """
    前端會帶 text, duration, frame_rate, seed, image
    傳到這裡，由本後端呼叫 ComfyUI 生成影片後搬移檔案，
    最後回傳 JSON。
    """
    # 解析表單參數
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "請提供有效的提示詞"}), 400

    try:
        duration = int(request.form.get("duration", 4))
    except ValueError:
        duration = 4

    try:
        frame_rate = int(request.form.get("frame_rate", 8))
    except ValueError:
        frame_rate = 8

    try:
        seed = int(request.form.get("seed", 0))
    except ValueError:
        seed = 0
    if seed == 0:
        # 若種子=0，則自動生成一個
        seed = int(time.time() * 1000) % 1000000

    image = request.files.get("image")
    if image is None:
        return jsonify({"error": "請上傳圖片"}), 400

    # 儲存上傳圖片
    filename = secure_filename(f"{uuid.uuid4().hex}_{image.filename}")
    temp_upload_dir = r"D:\sd1.5_img2video_temp_uploads"
    os.makedirs(temp_upload_dir, exist_ok=True)
    file_path = os.path.join(temp_upload_dir, filename)
    image.save(file_path)
    print("上傳圖片儲存於:", file_path)

    result = {}

    def call_comfyui():
        """
        生成核心邏輯：更新 workflow → queue_prompt → wait_for_completion → 搬移 → 回傳結果
        """
        try:
            # 1) 載入基礎工作流程
            workflow = json.loads(prompt_text)

            # 2) 更新工作流程
            if "61" in workflow and "text" in workflow["61"]["inputs"]:
                workflow["61"]["inputs"]["text"] = text
            # 假設 "183" 是控制 multiply_by (這裡依照你的實際 workflow 做修改)
            if "183" in workflow and "multiply_by" in workflow["183"]["inputs"]:
                workflow["183"]["inputs"]["multiply_by"] = duration * 16
            if "261" in workflow and "frame_rate" in workflow["261"]["inputs"]:
                workflow["261"]["inputs"]["frame_rate"] = frame_rate
            # 假設 "277" 是 KSampler seed (依你的 workflow ID 修正)
            if "277" in workflow and "seed" in workflow["277"]["inputs"]:
                workflow["277"]["inputs"]["seed"] = seed

            print("最終 workflow =", json.dumps(workflow, indent=2, ensure_ascii=False))

            # 3) 呼叫 ComfyUI
            resp_json = queue_prompt(workflow)
            if not resp_json or "prompt_id" not in resp_json:
                print("ComfyUI API 回應錯誤")
                result["error"] = "ComfyUI API 回應錯誤"
                return
            prompt_id = resp_json["prompt_id"]
            print("取得 prompt_id:", prompt_id)

            # 4) 等待完成
            wait_for_completion(prompt_id)
            time.sleep(2)  # 給系統一點時間寫檔案

            # 5) 搬移 MP4 檔案
            mp4_filename = move_output_files(prompt_id)
            if not mp4_filename:
                result["error"] = "搬移影片失敗"
            else:
                # 回傳對外影片 URL
                video_url = f"https://api.picturesmagician.com/get_video/{mp4_filename}?t={int(time.time())}"
                print("影片生成成功，URL =", video_url)
                result["video_url"] = video_url

        except Exception as e:
            print("例外錯誤：", e)
            result["error"] = str(e)
        finally:
            # 刪除暫存檔
            try:
                os.remove(file_path)
            except Exception as e2:
                print("刪除暫存檔失敗：", e2)

    # 啟動後台執行緒
    thread = threading.Thread(target=call_comfyui)
    thread.start()

    # 以 SSE 回傳生成進度
    def sse_stream():
        progress = 0
        while thread.is_alive():
            msg = {"progress": progress, "message": "影片生成中..."}
            yield f"data: {json.dumps(msg)}\n\n"
            time.sleep(5)
            progress = min(progress + 10, 90)

        thread.join()
        if "video_url" in result:
            ok = {"progress": 100, "video_url": result["video_url"], "message": "影片生成完成！"}
            yield f"data: {json.dumps(ok)}\n\n"
        else:
            err = result.get("error", "未知錯誤")
            fail = {"progress": 100, "error": err, "message": "影片生成失敗"}
            yield f"data: {json.dumps(fail)}\n\n"
        # 移除原先多餘的 yield "\n"

    # 加入 SSE 回傳所需的標頭，參考文生影片做法
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return Response(sse_stream(), headers=headers, mimetype="text/event-stream")

# ------------------------------------------------------
# 取回影片檔案
# ------------------------------------------------------
@app.route("/get_video/<path:filename>", methods=["GET"])
def get_video(filename):
    """
    提供最終影片檔下載/播放
    """
    file_path = os.path.join(target_dir, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "檔案不存在"}), 404
    return send_from_directory(target_dir, filename)

if __name__ == "__main__":
    # 後端 Flask 監聽 0.0.0.0:5000
    app.run(host="0.0.0.0", port=5000, debug=False)
