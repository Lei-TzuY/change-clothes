import os
import json
from flask import Flask, Blueprint

# --------------------------
# 定義主 Blueprint
main_bp = Blueprint('main', __name__)

@main_bp.route('/ping')
def ping():
    print("📣 Got a ping")
    return "pong"

# --------------------------
# 載入 upload Blueprint
from app.routes.upload import bp as upload_bp

# --------------------------
# 讀入 workflow 模板
with open('workflow_API.json', 'r', encoding='utf-8') as f:
    WORKFLOW_TEMPLATE = json.load(f)

# 其他全域常數
COMFY_ADDR = "127.0.0.1:8188"
COMFY_OUTPUT = os.path.abspath("/home/st426/ComfyUI/output")

# --------------------------
# 建立 Flask App 的 factory
def create_app():
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), 'static'),
        template_folder=os.path.join(os.path.dirname(__file__), 'templates')
    )
    # 設定輸出目錄
    app.config['OUTPUT_DIR'] = COMFY_OUTPUT

    # 註冊 Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    return app

# --------------------------
# 程式進入點
if __name__ == "__main__":
    app = create_app()
    app.run(
        host="0.0.0.0",
        port=5020,
        debug=True,
        use_reloader=True
    )

