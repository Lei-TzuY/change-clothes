import os

BASE_DIR    = os.path.dirname(__file__)
UPLOAD1     = os.path.join(BASE_DIR, "received1")
UPLOAD2     = os.path.join(BASE_DIR, "received2")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")
COMFY_ADDR  = "127.0.0.1:8188"

BASE = '/home/st426/ComfyUI'
COMFY_OUTPUT = os.path.join(BASE, 'output')

# 確保資料夾存在
for d in (UPLOAD1, UPLOAD2, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)

