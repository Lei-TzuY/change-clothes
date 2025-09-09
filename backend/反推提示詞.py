import json
import os
import shutil
import time
import websocket  # 請確保已安裝 websocket-client (pip install websocket-client)
import urllib.request
import uuid
import base64  # 新增 base64 模組
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
from PIL import Image, PngImagePlugin  # 用來嵌入 dummy metadata

app = Flask(__name__)
CORS(app)

# =============================
# 設定區 (可考慮改用環境變數)
# =============================
# ComfyUI 伺服器與資料夾設定
SERVER_ADDRESS = "127.0.0.1:8188"  # ComfyUI 伺服器位址
COMFYUI_OUTPUT_DIR = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"  # ComfyUI 輸出資料夾路徑
TARGET_DIR = r"D:\圖像反推"  # 目標資料夾路徑，將搬移 txt 文檔到此處
os.makedirs(TARGET_DIR, exist_ok=True)

# 上傳圖片暫存資料夾 (若需要，可新增)
TEMP_DIR = r"D:\大模型\temp_input"
os.makedirs(TEMP_DIR, exist_ok=True)

# 外部對應域名 (供前端存取圖片用)
EXTERNAL_API_URL = "https://reverseprompt.picturesmagician.com"

# WebSocket 等待超時秒數
WS_TIMEOUT = 180

# =============================
# 輔助函式
# =============================

def queue_prompt(prompt):
    """
    將工作流程 (Workflow) JSON 送往 ComfyUI 的 /prompt API，
    並回傳包含 prompt_id 與任務專用 client_id 的結果。
    """
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": prompt,
        "client_id": client_id
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{SERVER_ADDRESS}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            result["client_id"] = client_id
            return result
    except Exception as e:
        print(f"❌ 無法連線至 ComfyUI API: {e}")
        return None

def wait_for_completion(prompt_id, client_id):
    """
    建立 WebSocket 連線以監聽指定 prompt_id 的執行狀態，
    當收到 'executing' 訊息，且其中的 node 為 None 且 prompt_id 相符時，
    表示該流程已完成。
    加入超時處理避免無限等待。
    """
    ws_url = f"ws://{SERVER_ADDRESS}/ws?clientId={client_id}"
    print("🕐 等待 ComfyUI 任務完成...")
    start_time = time.time()
    try:
        ws = websocket.create_connection(ws_url, timeout=30)
        while True:
            if time.time() - start_time > WS_TIMEOUT:
                print("⚠️ 等待任務超時")
                break
            out = ws.recv()
            if isinstance(out, str):
                try:
                    message = json.loads(out)
                except Exception as e:
                    print(f"❌ JSON 解碼錯誤: {e}")
                    continue
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
    透過 /history/<prompt_id> API 取得該任務的輸出紀錄，
    並回傳相對應的 JSON 資料。
    """
    url = f"http://{SERVER_ADDRESS}/history/{prompt_id}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            history_data = json.loads(resp.read())
        print(f"📜 Debug: history API 回應 = {json.dumps(history_data, indent=4, ensure_ascii=False)}")
        return history_data.get(prompt_id, {})
    except Exception as e:
        print(f"❌ 無法取得歷史紀錄: {e}")
        return {}

def find_latest_txt():
    """
    若 /history API 未提供有效檔名，則於 ComfyUI 輸出資料夾中搜尋最新建立的 .txt 檔案。
    """
    try:
        txt_files = [f for f in os.listdir(COMFYUI_OUTPUT_DIR) if f.lower().endswith(".txt")]
    except Exception as e:
        print(f"❌ 無法讀取輸出目錄: {e}")
        return None
    if not txt_files:
        print("🚫 找不到任何 .txt 檔案！")
        return None
    latest_txt = max(txt_files, key=lambda f: os.path.getctime(os.path.join(COMFYUI_OUTPUT_DIR, f)))
    print(f"🎞 找到最新的 .txt 檔案: {latest_txt}")
    return latest_txt

def get_final_text_filename(prompt_id):
    """
    嘗試從 /history/<prompt_id> 的回應中取得最終儲存的文本檔案名稱，
    若無法取得，則改用檔案搜尋方式取得最新 .txt 檔案。
    """
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_txt()
    outputs = history.get("outputs", {})
    text_node = outputs.get("4", {})
    if "images" in text_node:
        for info in text_node["images"]:
            filename = info.get("filename")
            if filename and filename.lower().endswith(".txt"):
                print(f"🎞 從 API 取得文本檔名: {filename}")
                return filename
    print("⚠️ /history API 未提供文本檔名，改用檔案搜尋。")
    return find_latest_txt()

def move_output_files(prompt_id):
    """
    取得最終儲存的文本檔名後，將該 .txt 檔從 ComfyUI 輸出資料夾搬移至指定目標資料夾中。
    """
    text_filename = get_final_text_filename(prompt_id)
    if not text_filename:
        print("🚫 無法取得文本檔案名稱！")
        return None
    source_path = os.path.join(COMFYUI_OUTPUT_DIR, text_filename)
    target_path = os.path.join(TARGET_DIR, text_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return None
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
        return text_filename
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")
        return None

# =============================
# 定義 API 工作流程 (Workflow) JSON
# =============================
prompt_text = r"""
{
  "2": {
    "inputs": {
      "model": "wd-v1-4-moat-tagger-v2",
      "threshold": 0.35,
      "character_threshold": 0.85,
      "replace_underscore": false,
      "trailing_comma": false,
      "exclude_tags": "",
      "tags": "outdoors, sky, day, tree, no_humans, grass, plant, building, scenery, fence, road, bush, house",
      "image": [
        "5",
        0
      ]
    },
    "class_type": "WD14Tagger|pysssss",
    "_meta": {
      "title": "WD14圖像反推提詞"
    }
  },
  "3": {
    "inputs": {
      "text": [
        "2",
        0
      ],
      "text2": "outdoors, sky, day, tree, no_humans, grass, plant, building, scenery, fence, road, bush, house"
    },
    "class_type": "ShowText|pysssss",
    "_meta": {
      "title": "顯示文本"
    }
  },
  "4": {
    "inputs": {
      "text": [
        "3",
        0
      ],
      "path": "./ComfyUI/output",
      "filename_prefix": "ComfyUI",
      "filename_delimiter": "_",
      "filename_number_padding": 4,
      "file_extension": ".txt",
      "encoding": "utf-8",
      "filename_suffix": ""
    },
    "class_type": "Save Text File",
    "_meta": {
      "title": "儲存文本"
    }
  },
  "5": {
    "inputs": {
      "image_path": "C:\\Users\\User\\Desktop\\00001-2890787883.png"
    },
    "class_type": "ZwngLoadImagePathOrURL",
    "_meta": {
      "title": "Load Image Path or URL"
    }
  },
  "6": {
    "inputs": {
      "images": [
        "5",
        0
      ]
    },
    "class_type": "PreviewImage",
    "_meta": {
      "title": "預覽圖像"
    }
  }
}
"""

try:
    workflow = json.loads(prompt_text)
except json.decoder.JSONDecodeError as e:
    print(f"❌ JSON 格式錯誤: {e}")
    exit()

# =============================
# 修改工作流程中的參數
# =============================
workflow["2"]["inputs"]["threshold"] = 0.35
workflow["2"]["inputs"]["character_threshold"] = 0.85

# =============================
# Flask 路由
# =============================

@app.route("/reverse_prompt", methods=["POST"])
def reverse_prompt():
    """
    接收前端傳來的圖像（base64 格式，JSON key 為 "image"），
    將圖像存至暫存目錄，更新工作流程中節點 "5" 的 image_path，
    呼叫 ComfyUI 產生反推文本，
    搬移生成的文本檔至目標資料夾，
    並回傳對外的 HTTPS 連結。
    """
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "缺少 image 參數"}), 400

    # 前端上傳圖像 (base64 格式) 解碼後存檔
    try:
        image_data = data["image"]
        # 輸出除錯用：檢查是否包含 base64 前綴
        print("🔹 收到圖片資料:", image_data[:30])
        if "," in image_data:
            header, encoded = image_data.split(",", 1)
        else:
            encoded = image_data
        filename = f"reverse_{uuid.uuid4().hex}.png"
        image_path = os.path.join(TEMP_DIR, filename)
        with open(image_path, "wb") as f:
            f.write(base64.b64decode(encoded))
        print(f"✅ 上傳圖像存檔：{image_path}")

        # 利用 Pillow 嵌入 dummy workflow metadata 避免 ComfyUI 檢查 extra_pnginfo 時出錯
        try:
            with Image.open(image_path) as im:
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("workflow", "{}")
                im.save(image_path, pnginfo=metadata)
            print("✅ 嵌入 dummy workflow metadata 成功")
        except Exception as e:
            print(f"❌ 嵌入 metadata 失敗: {e}")
    except Exception as e:
        return jsonify({"error": "圖像解碼失敗", "details": str(e)}), 400

    # 更新工作流程中節點 "5" 的 image_path
    workflow["5"]["inputs"]["image_path"] = image_path

    # 若前端有其他參數 (例如 threshold)，可在此更新
    workflow["2"]["inputs"]["threshold"] = float(data.get("threshold", 0.35))
    workflow["2"]["inputs"]["character_threshold"] = float(data.get("character_threshold", 0.85))

    # 呼叫 ComfyUI
    print("🚀 發送工作流程到 ComfyUI...")
    resp = queue_prompt(workflow)
    if not resp or "prompt_id" not in resp:
        return jsonify({"error": "ComfyUI API 回應錯誤"}), 500

    prompt_id = resp["prompt_id"]
    client_id = resp["client_id"]
    print(f"🆔 取得 prompt_id: {prompt_id}")

    # 等待工作流程完成
    wait_for_completion(prompt_id, client_id)
    time.sleep(2)  # 可根據情況微調等待時間

    # 取得並搬移生成的文本檔案
    final_filename = move_output_files(prompt_id)
    if not final_filename:
        return jsonify({"error": "搬移檔案失敗，未取得文本檔名"}), 500

    # 組合對外網址 (加入時間戳避免快取問題)
    text_url = f"{EXTERNAL_API_URL}/get_image/{final_filename}?t={int(time.time())}"
    print("🔹 回傳文本 URL:", text_url)
    return jsonify({"text_url": text_url})

@app.route("/get_image/<path:filename>", methods=["GET"])
def get_image(filename):
    """
    提供搬移後的檔案下載或顯示 (通常為 .txt)。
    """
    file_path = os.path.join(TARGET_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "檔案不存在"}), 404
    response = make_response(send_from_directory(TARGET_DIR, filename))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

# =============================
# 啟動 Flask 服務
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5007, debug=False)
