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
comfyui_output_dir = r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"  # ComfyUI 輸出資料夾路徑
target_dir = r"D:\圖像反推"  # 目標資料夾路徑，將搬移 txt 文檔到此處
os.makedirs(target_dir, exist_ok=True)  # 確保目標資料夾存在

# =============================
# 函式定義
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
    建立 WebSocket 連線以監聽指定 prompt_id 的執行狀態。
    當收到 'executing' 訊息，且其中的 node 為 None 且 prompt_id 相符時，
    表示該流程已完成。
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
    透過 /history/<prompt_id> API 取得該任務的輸出紀錄，
    並回傳相對應的 JSON 資料。
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

def find_latest_txt():
    """
    若 /history API 未提供有效檔名，則於 ComfyUI 輸出資料夾中搜尋最新建立的 .txt 檔案。
    """
    txt_files = [f for f in os.listdir(comfyui_output_dir) if f.lower().endswith(".txt")]
    if not txt_files:
        print("🚫 找不到任何 .txt 檔案！")
        return None
    latest_txt = max(txt_files, key=lambda f: os.path.getctime(os.path.join(comfyui_output_dir, f)))
    print(f"🎞 找到最新的 .txt 檔案: {latest_txt}")
    return latest_txt

def get_final_text_filename(prompt_id):
    """
    嘗試從 /history/<prompt_id> 的回應中取得最終儲存的文本檔案名稱，
    但若無法取得（如回應中未提供檔名），則改用檔案搜尋方式取得最新 .txt 檔案。
    """
    history = get_history(prompt_id)
    if not history:
        print("⚠️ /history API 回應為空，改用檔案搜尋。")
        return find_latest_txt()
    outputs = history.get("outputs", {})
    # 嘗試從預設的儲存文本節點（例如節點 "4"）取得檔案名稱
    text_node = outputs.get("4", {})
    # 由於 /history API 回應中沒有提供檔案名稱，這裡通常不會取得結果
    if "images" in text_node:
        for info in text_node["images"]:
            filename = info.get("filename")
            if filename and filename.lower().endswith(".txt"):
                print(f"🎞 從 API 取得文本檔名: {filename}")
                return filename
    # 若無法取得檔名，則採用檔案搜尋
    print("⚠️ /history API 未提供文本檔名，改用檔案搜尋。")
    return find_latest_txt()

def move_output_files(prompt_id):
    """
    取得最終儲存的文本檔名後，
    將該 .txt 檔從 ComfyUI 輸出資料夾搬移至指定目標資料夾中。
    """
    text_filename = get_final_text_filename(prompt_id)
    if not text_filename:
        print("🚫 無法取得文本檔案名稱！")
        return
    source_path = os.path.join(comfyui_output_dir, text_filename)
    target_path = os.path.join(target_dir, text_filename)
    if not os.path.exists(source_path):
        print(f"⚠️ 找不到 {source_path}，無法搬移！")
        return
    try:
        shutil.move(source_path, target_path)
        print(f"✅ 已搬移: {source_path} → {target_path}")
    except Exception as e:
        print(f"❌ 搬移失敗: {e}")

# =============================
# 定義 API 工作流程 (Workflow) JSON
# =============================
# 使用原始字串 (在前面加上 r) 以避免跳脫字元錯誤
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

# 將 JSON 字串轉換成 Python dict 物件
try:
    prompt = json.loads(prompt_text)
except json.decoder.JSONDecodeError as e:
    print(f"❌ JSON 格式錯誤: {e}")
    exit()

# =============================
# 修改 prompt 中的參數，確保結構符合 ComfyUI 的預期
# =============================
# 設定圖像路徑（請確認路徑正確）
prompt["5"]["inputs"]["image_path"] = r"C:\Users\User\Desktop\00001-2890787883.png"
# 設定信心度參數
prompt["2"]["inputs"]["threshold"] = 0.35
prompt["2"]["inputs"]["character_threshold"] = 0.85

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

# 等待工作流程完成
wait_for_completion(prompt_id, client_id)

print("✅ 任務正常完成，將搬移輸出結果（文本檔）到指定路徑。")
move_output_files(prompt_id)
