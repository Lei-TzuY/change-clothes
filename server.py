import json
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5020, debug=True, use_reloader=True)

# 在這裡加入
with open('workflow_API.json', 'r', encoding='utf-8') as f:
    WORKFLOW_TEMPLATE = json.load(f)

COMFY_ADDR   = "127.0.0.1:8188"
COMFY_OUTPUT = "/home/st426/ComfyUI/output"   # <--- 補上這個閉合的引號

