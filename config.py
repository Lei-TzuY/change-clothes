import os

BASE_DIR    = os.path.dirname(__file__)
UPLOAD1     = os.path.join(BASE_DIR, "received1")
UPLOAD2     = os.path.join(BASE_DIR, "received2")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")
COMFY_ADDR  = os.getenv("COMFY_ADDR", "127.0.0.1:8188")

# Flask secret key (override via env SECRET_KEY)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-this")

# Database (override via env DATABASE_URL)
_default_sqlite = f"sqlite:///{os.path.join(BASE_DIR, 'change_clothes.db')}"
SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", _default_sqlite)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# reCAPTCHA keys (provide your own Site/Secret keys)
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "")

# COMFY_OUTPUT：優先讀取環境變數；
# 未設定時 Windows 預設使用本專案 output/，其他系統維持既有預設。
if os.getenv("COMFY_OUTPUT"):
    COMFY_OUTPUT = os.getenv("COMFY_OUTPUT")
else:
    if os.name == "nt":
        COMFY_OUTPUT = os.path.join(BASE_DIR, "output")
    else:
        COMFY_OUTPUT = os.path.join('/home/st426/ComfyUI', 'output')

# 確保資料夾存在
for d in (UPLOAD1, UPLOAD2, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)
