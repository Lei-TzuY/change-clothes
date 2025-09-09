import os
from dotenv import load_dotenv

# 先載入 .env（如果你想用檔案管理環境變數）
load_dotenv()

# ComfyUI API endpoint
COMFYUI_API_URL = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:8188")

# ComfyUI 的輸出資料夾（圖片產出路徑）
COMFYUI_OUTPUT_DIR = os.getenv(
    "COMFYUI_OUTPUT_DIR",
    r"D:\comfyui\ComfyUI_windows_portable\ComfyUI\output"
)

# 最終要搬到哪裡、供前端透過 /get_image 讀取
TARGET_DIR = os.getenv("TARGET_DIR", r"D:\大模型文生圖")

# 對外組成 image_url 的基底網址
EXTERNAL_URL = os.getenv(
    "EXTERNAL_URL",
    "https://api.picturesmagician.com"
)

# CORS 白名單（正式版建議不要是 "*"）
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
