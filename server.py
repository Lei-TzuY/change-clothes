# import os
# import json
# from flask import Flask, Blueprint

# # --------------------------
# # 定義主 Blueprint
# main_bp = Blueprint('main', __name__)

# @main_bp.route('/ping')
# def ping():
#     print("📣 Got a ping")
#     return "pong"

# # --------------------------
# # 載入 upload Blueprint
# from app.routes.upload import bp as upload_bp

# # --------------------------
# # 讀入 workflow 模板
# with open('workflow_API.json', 'r', encoding='utf-8') as f:
#     WORKFLOW_TEMPLATE = json.load(f)

# # 其他全域常數
# COMFY_ADDR = "127.0.0.1:8188"
# COMFY_OUTPUT = os.path.abspath("/home/st426/ComfyUI/output")

# # --------------------------
# # 建立 Flask App 的 factory
# def create_app():
#     app = Flask(
#         __name__,
#         static_folder=os.path.join(os.path.dirname(__file__), 'static'),
#         template_folder=os.path.join(os.path.dirname(__file__), 'templates')
#     )
#     # 設定輸出目錄
#     app.config['OUTPUT_DIR'] = COMFY_OUTPUT

#     # 註冊 Blueprints
#     app.register_blueprint(main_bp)
#     app.register_blueprint(upload_bp)
#     return app

# # --------------------------
# # 程式進入點
# if __name__ == "__main__":
#     app = create_app()
#     app.run(
#         host="0.0.0.0",
#         port=5020,
#         debug=True,
#         use_reloader=True
#     )


#舊版
# import json
# from app import create_app

# app = create_app()

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5020, debug=True, use_reloader=True)

# # 在這裡加入
# with open('workflow_API.json', 'r', encoding='utf-8') as f:
#     WORKFLOW_TEMPLATE = json.load(f)

# COMFY_ADDR   = "127.0.0.1:8188"
# COMFY_OUTPUT = "/home/st426/ComfyUI/output"   # <--- 補上這個閉合的引號

# server.py
import os
import json
from pathlib import Path
from flask import Flask, Blueprint, render_template, send_from_directory
from app.extensions import db, login_manager
from app.models import User

# --------------------------
# 專案路徑
BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "app"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# --------------------------
# 主 Blueprint
main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    # 若有 templates/index.html 就會渲染；沒有就回一段字
    # try:
        return render_template("index.html")
    # except Exception:
        # return "It works. Add templates/index.html to customize."

@main_bp.route("/favicon.ico")
def favicon():
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent / "app" / "static"
    return send_from_directory(static_dir, "favicon.ico")

@main_bp.route("/ping")
def ping():
    print("📣 Got a ping")
    return "pong"

@main_bp.route("/outputs/<path:filename>")
def serve_output(filename):
    from flask import current_app
    return send_from_directory(current_app.config["OUTPUT_DIR"], filename)

# --------------------------
# 讀取 workflow 模板（相對路徑，若不存在就給預設）
WORKFLOW_PATH = BASE_DIR / "workflow_API.json"
try:
    with WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        WORKFLOW_TEMPLATE = json.load(f)
except FileNotFoundError:
    print(f"⚠️ workflow_API.json 不存在：{WORKFLOW_PATH}")
    WORKFLOW_TEMPLATE = {}

# --------------------------
# 其他全域常數
COMFY_ADDR = os.getenv("COMFY_ADDR", "127.0.0.1:8188")

# COMFY_OUTPUT：優先讀環境變數；否則：
# - Windows：專案根目錄下的 output/
# - Linux/mac：沿用你原來的預設 /home/st426/ComfyUI/output
if os.getenv("COMFY_OUTPUT"):
    COMFY_OUTPUT = Path(os.getenv("COMFY_OUTPUT"))
else:
    if os.name == "nt":
        COMFY_OUTPUT = BASE_DIR / "output"
    else:
        COMFY_OUTPUT = Path("/home/st426/ComfyUI/output")

# 確保目錄存在
COMFY_OUTPUT = COMFY_OUTPUT.resolve()
COMFY_OUTPUT.mkdir(parents=True, exist_ok=True)

# --------------------------
# 建立 Flask App（factory）
def create_app():
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        template_folder=str(TEMPLATES_DIR),
    )

    # 設定輸出目錄
    # Load config and output dir
    try:
        app.config.from_object('config')
    except Exception:
        pass
    app.config["OUTPUT_DIR"] = str(COMFY_OUTPUT)

    # Init DB and Login
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # 註冊 Blueprints
    app.register_blueprint(main_bp)

    # 延遲匯入，避免循環 import
    from app.routes.upload import bp as upload_bp
    app.register_blueprint(upload_bp)

    # additional features and pages
    try:
        from app.routes.features import bp as features_bp
        app.register_blueprint(features_bp)
    except Exception:
        pass

    try:
        from app.routes.pages import bp as pages_bp
        app.register_blueprint(pages_bp)
    except Exception:
        pass

    # Auth blueprint
    try:
        from app.routes.auth import bp as auth_bp
        app.register_blueprint(auth_bp, url_prefix="/auth")
    except Exception as e:
        # Make failures visible to avoid silent BuildError in templates
        print(f"Auth blueprint failed to load: {e}")

    # 健康檢查
    @app.get("/healthz")
    def healthz():
        return "ok"

    # Ensure tables exist
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

    return app

# --------------------------
# 程式進入點
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5020, debug=True, use_reloader=True)
