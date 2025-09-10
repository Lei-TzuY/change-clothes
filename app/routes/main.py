# app/routes/main.py
import os
import glob
from flask import Blueprint, current_app, render_template, url_for, send_from_directory, Response

bp = Blueprint('main', __name__)
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

@bp.route('/')
def index():
    output_dir = current_app.config['OUTPUT_DIR']
    # 確保資料夾存在
    os.makedirs(output_dir, exist_ok=True)

    # 列出所有 .png
    files = [f for f in os.listdir(output_dir) if f.lower().endswith('.png')]
    latest_url = None
    if files:
        # 取最新
        latest = max(files, key=lambda fn: os.path.getctime(os.path.join(output_dir, fn)))
        # 生成 /outputs/<filename> 的 URL
        latest_url = url_for('main.serve_output', filename=latest)

    return render_template('index.html', latest_url=latest_url)

@bp.route('/outputs/<path:filename>')
def serve_output(filename):
    # 從 OUTPUT_DIR 讀檔案並回傳
    return send_from_directory(current_app.config['OUTPUT_DIR'], filename)


@bp.route('/favicon.ico')
def favicon():
    static_dir = current_app.static_folder
    # Prefer .ico, then .png, finally .svg
    for name, mimetype in (
        ('favicon.ico', 'image/vnd.microsoft.icon'),
        ('favicon.png', 'image/png'),
        ('favicon.svg', 'image/svg+xml'),
    ):
        try:
            return send_from_directory(static_dir, name, mimetype=mimetype)
        except Exception:
            continue
    return Response(status=404)

