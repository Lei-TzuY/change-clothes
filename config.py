import os

BASE_DIR    = os.path.dirname(__file__)
UPLOAD1     = os.path.join(BASE_DIR, "received1")
UPLOAD2     = os.path.join(BASE_DIR, "received2")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")
COMFY_ADDR  = os.getenv("COMFY_ADDR", "127.0.0.1:8188")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-this")

_default_sqlite = f"sqlite:///{os.path.join(BASE_DIR, 'change_clothes.db')}"
SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", _default_sqlite)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Test/limits toggles
TEST_MODE = os.getenv("TEST_MODE", "0") == "1"
DISABLE_DAILY_FREE_LIMIT = (os.getenv("DISABLE_DAILY_FREE_LIMIT", "0") == "1") or TEST_MODE
DISABLE_RATELIMIT = (os.getenv("DISABLE_RATELIMIT", "0") == "1") or TEST_MODE
# Flask-Limiter respects this flag
RATELIMIT_ENABLED = not DISABLE_RATELIMIT

# ✅ 正確：用環境變數名稱讀值
RECAPTCHA_SITE_KEY   = os.getenv("6LcWrsMrAAAAAB-skctSJXUhCyDyj8vH4l0B-sB7", "")
RECAPTCHA_SECRET_KEY = os.getenv("6LcWrsMrAAAAAIEYZfkGuX2uTDnXD1BKSGK65-pe", "")

# 若在中國大陸等地可能需要 recaptcha.net
RECAPTCHA_SCRIPT_DOMAIN = os.getenv("RECAPTCHA_SCRIPT_DOMAIN", "www.google.com")

# 本機或開發時使用 Google 官方「測試金鑰」
# test site:   6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI
# test secret: 6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe
RECAPTCHA_USE_TEST_KEYS = os.getenv("RECAPTCHA_USE_TEST_KEYS", "0") == "1"
if RECAPTCHA_USE_TEST_KEYS:
    RECAPTCHA_SITE_KEY   = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
    RECAPTCHA_SECRET_KEY = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"

MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "20")) * 1024 * 1024

CKPT_NAME = os.getenv("CKPT_NAME", "meinamix_v12Final.safetensors")
VAE_NAME = os.getenv("VAE_NAME")

MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "0") == "1"
MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "0") == "1"
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_SENDER = os.getenv("MAIL_SENDER", "noreply@localhost")
SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "dev-email-verify-salt")
MAIL_DEV_PRINT = os.getenv("MAIL_DEV_PRINT", "0") == "1"

if os.getenv("COMFY_OUTPUT"):
    COMFY_OUTPUT = os.getenv("COMFY_OUTPUT")
else:
    # Try to auto-detect common ComfyUI output locations
    if os.name == "nt":
        parent = os.path.dirname(BASE_DIR)
        win_guess = os.path.join(parent, "ComfyUI_windows_portable", "ComfyUI", "output")
        if os.path.isdir(win_guess):
            COMFY_OUTPUT = win_guess
        else:
            COMFY_OUTPUT = os.path.join(BASE_DIR, "output")
    else:
        linux_guess = os.path.join(os.path.expanduser("~"), "ComfyUI", "output")
        COMFY_OUTPUT = linux_guess if os.path.isdir(linux_guess) else os.path.join("/home/st426/ComfyUI", "output")

for d in (UPLOAD1, UPLOAD2, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)
