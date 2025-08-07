import os
from flask import Blueprint, current_app, render_template, url_for

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    # 1. 取出絕對路徑的 OUTPUT_DIR（假設裡面放的是 .png）
    output_dir = current_app.config['OUTPUT_DIR']

    # 2. 列出所有 png 檔
    files = [
        fn for fn in os.listdir(output_dir)
        if fn.lower().endswith('.png')
    ]

    # 3. 沒圖就傳 None
    if not files:
        latest_url = None
    else:
        # 4. 挑最新的檔名
        latest = max(
            files,
            key=lambda fn: os.path.getctime(os.path.join(output_dir, fn))
        )

        # 5. 計算相對於 static folder 的路徑
        #    current_app.static_folder 會是 ".../yourapp/static"
        static_root = current_app.static_folder
        rel_dir = os.path.relpath(output_dir, static_root)  # e.g. "output"

        # 6. 用 url_for 生成可直接在 <img> 用的 URL
        latest_url = url_for('static', filename=f'{rel_dir}/{latest}')

    # 7. 傳給模板
    return render_template('index.html', latest_url=latest_url)

