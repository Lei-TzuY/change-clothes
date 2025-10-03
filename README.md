# change-clothes / Picture Magician

一個基於 Flask 的圖片處理與虛擬換衣實驗專案，整合：
- 前端頁面（上傳人像、上傳衣服／素材、顯示結果）
- 與 ComfyUI 的工作流整合（Text2Image、Image2Image、Inpaint）
- 後端 API（上傳、觸發推論、輸出檔案存取）
<<<<<<< HEAD
- 帳戶系統（註冊／登入／登出／修改密碼／個人資料）
- reCAPTCHA 驗證（註冊須通過）
- SQLite（預設）或自訂資料庫（SQLAlchemy）
 - CSRF 防護（Flask‑WTF）與基本 Rate Limit（Flask‑Limiter）
=======
- 帳戶系統（註冊／登入／登出）
- reCAPTCHA 驗證（註冊須通過）
- SQLite（預設）或自訂資料庫（SQLAlchemy）
>>>>>>> origin/main

## 快速開始
1) 建立與啟用虛擬環境
- Windows (PowerShell)
  ```powershell
  python -m venv venv
  venv\Scripts\Activate
  ```
- macOS/Linux (bash)
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

2) 安裝套件
```bash
pip install -r requirements.txt
```

3) 設定環境變數（至少建議設定 SECRET_KEY，註冊需 reCAPTCHA）
- Windows (PowerShell)
  ```powershell
  $env:SECRET_KEY = "change-me"
  $env:RECAPTCHA_SITE_KEY = "<your_site_key>"
  $env:RECAPTCHA_SECRET_KEY = "<your_secret_key>"
  # 選用：資料庫與 ComfyUI 設定
  $env:DATABASE_URL = "sqlite:///change_clothes.db"  # 預設即為此
  $env:COMFY_ADDR = "127.0.0.1:8188"
  $env:COMFY_OUTPUT = ".\output"  # Windows 預設為專案 output 資料夾
  ```
- macOS/Linux (bash)
  ```bash
  export SECRET_KEY="change-me"
  export RECAPTCHA_SITE_KEY="<your_site_key>"
  export RECAPTCHA_SECRET_KEY="<your_secret_key>"
  # 選用：資料庫與 ComfyUI 設定
  export DATABASE_URL="sqlite:///change_clothes.db"
  export COMFY_ADDR="127.0.0.1:8188"
  export COMFY_OUTPUT="./output"
  ```

4) 啟動 ComfyUI（請自行啟動，確保能以 `COMFY_ADDR` 存取）

5) 啟動後端（預設埠 5020）
```bash
python server.py
# 或
FLASK_APP=server.py flask run --host=0.0.0.0 --port=5020
```

瀏覽器開啟 http://localhost:5020

## 主要功能與路由
- 頁面
  - `/` 首頁（上傳與最新結果顯示）
  - `/t2i` 文生圖頁面
  - `/i2i` 圖生圖頁面
  - `/inpaint` 局部修復頁面
- 帳戶
  - `GET /auth/register` 註冊頁（含 reCAPTCHA）
  - `POST /auth/register` 送出註冊
<<<<<<< HEAD
  - `GET /auth/login` 登入頁（支援「記住我」）
  - `POST /auth/login` 送出登入
  - `POST /auth/logout` 登出
  - `GET /auth/profile` 帳戶資料
  - `GET /auth/password` 更改密碼頁
  - `POST /auth/password` 送出更改密碼
=======
  - `GET /auth/login` 登入頁
  - `POST /auth/login` 送出登入
  - `POST /auth/logout` 登出
>>>>>>> origin/main
- API（部分）
  - `POST /upload1` 上傳人像
  - `POST /upload2` 上傳衣服並觸發合成
  - `POST /text2image`、`POST /img2img`、`POST /inpaint`
  - `GET /outputs/<path:filename>` 讀取輸出
  - `GET /ping`、`GET /healthz` 健康檢查

## 組態說明
專案會讀取 `config.py` 與環境變數：
- `SECRET_KEY`：Flask 簽章金鑰（務必在正式環境設定）
- `DATABASE_URL`：SQLAlchemy 連線字串，預設 `sqlite:///change_clothes.db`
- `RECAPTCHA_SITE_KEY`、`RECAPTCHA_SECRET_KEY`：Google reCAPTCHA v2 金鑰（註冊必填）
- `COMFY_ADDR`：ComfyUI 位置，預設 `127.0.0.1:8188`
- `COMFY_OUTPUT`：ComfyUI 輸出目錄；Windows 預設為專案 `output/`
- `OUTPUT_DIR`：後端輸出檔案服務的根目錄（由 `config.py` 設定）
<<<<<<< HEAD
 - `RECAPTCHA_SCRIPT_DOMAIN`：reCAPTCHA 載入網域，預設 `www.google.com`，中國網路可用 `www.recaptcha.net`
 - `RECAPTCHA_USE_TEST_KEYS`：本機開發可設 `1` 使用 Google 測試金鑰
 - `MAX_CONTENT_LENGTH_MB`：上傳檔案大小上限（MB，預設 20）
=======
>>>>>>> origin/main

資料表會在啟動時自動 `create_all()` 建立（SQLite 預設）。如需版本控管建議導入 Alembic。

## 專案結構（擇要）
- `server.py`：應用程式入口（也會註冊藍圖與建表）
- `config.py`：配置與環境變數讀取
- `app/extensions.py`：SQLAlchemy、LoginManager 初始化
- `app/models.py`：資料模型（`User`）
- `app/routes/`
  - `upload.py`：上傳與合成流程 API
  - `features.py`：Text2Image / Image2Image / Inpaint API
  - `pages.py`：對應頁面路由
  - `auth.py`：註冊／登入／登出
- `app/templates/`：`index.html`、`_nav.html`、`login.html`、`register.html`、`t2i.html`、`i2i.html`、`inpaint.html`
- `app/static/`：前端樣式與腳本
- `workflow_API.json`：ComfyUI 工作流模板

## 常見問題（Troubleshooting）
- BuildError：`auth.login_form` 無法建立 URL
  - 請確認使用同一個 venv 啟動，並已安裝需求：`venv\Scripts\python.exe -m pip install -r requirements.txt`
  - 重新啟動伺服器；啟動時若出現 `Auth blueprint failed to load: ...`，依訊息安裝遺漏套件或修正錯誤。
- 註冊總是失敗
  - 未設定 reCAPTCHA 金鑰或驗證未通過；請在環境變數或 `config.py` 設定 `RECAPTCHA_*`。
- 生成沒有輸出／無法顯示最新影像
  - 確認 `COMFY_ADDR` 指向正確、ComfyUI 正在運行；並檢查 `COMFY_OUTPUT` 是否可存取且有新檔案。
- 路由 404 或頁面樣式錯亂
  - 清除瀏覽器快取，或確認進程實際載入的是 `server.py` 版本的 app。

## 開發建議
<<<<<<< HEAD
- 已啟用 CSRF 與基本 Rate Limit；上線建議改用 Redis 等外部儲存作為限流 backend（`storage_uri`）。
=======
- 預設未啟用 CSRF；若要表單更安全，建議導入 Flask‑WTF。
>>>>>>> origin/main
- 若要部署正式環境，請：
  - 設定強隨機的 `SECRET_KEY`
  - 使用正式的資料庫（`DATABASE_URL`）與遷移工具（Alembic）
  - 以 WSGI 伺服器（例如 gunicorn/uwsgi）執行，並放在反向代理後方

---
如需我幫你加入 CSRF、防爆量（Rate Limit）或 Docker 化，告訴我你偏好的方向即可。
# Picture-Magician
