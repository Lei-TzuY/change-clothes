#!/usr/bin/env bash
#
# run_server.sh — 一鍵啟動虛擬試衣間 Flask 伺服器

# 1. 切到專案資料夾（請改成你的路徑）
cd /home/st426/change-clothes

# 2. 啟用 virtualenv（若沒有可以略過或改成你的 env 名稱）
if [ -f venv/bin/activate ]; then
  source venv/bin/activate
fi

# 3. 設定 Flask 參數（開發模式、自動重載）
export FLASK_APP=server.py
export FLASK_ENV=development
export FLASK_DEBUG=1

# 4. 執行 Flask（也可以改成 python server.py）
python -m flask run --host=0.0.0.0 --port=5020

# 結束後，可按 Ctrl+C 停止

