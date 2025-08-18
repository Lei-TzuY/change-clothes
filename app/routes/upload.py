import os
import json
import copy
import time
import uuid
import shutil
import urllib.request
import websocket
import logging
from flask import Blueprint, request, jsonify, current_app, url_for
from config import UPLOAD1, UPLOAD2, OUTPUT_DIR, COMFY_ADDR, COMFY_OUTPUT

# 定義 Blueprint
bp = Blueprint('upload', __name__)
last_person = {'path': None}

# 讀取 workflow 模板
WF_PATH = os.path.join(os.getcwd(), 'workflow_API.json')
with open(WF_PATH, 'r', encoding='utf-8') as f:
    WORKFLOW_TEMPLATE = json.load(f)

@bp.route('/upload1', methods=['POST'])
def upload1():
    if 'image' not in request.files:
        return jsonify(error='請用 multipart/form-data 並帶 image 欄位'), 400

    img = request.files['image']
    fn = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    save_path = os.path.join(UPLOAD1, fn)
    img.save(save_path)
    last_person['path'] = save_path
    return jsonify(message='人物圖已接收', path=save_path), 200

@bp.route('/upload2', methods=['POST'])
def upload2_and_run_comfy():
    if not last_person['path']:
        return jsonify(error='請先上傳人物圖'), 400
    if 'image' not in request.files:
        return jsonify(error='請用 multipart/form-data 並帶 image 欄位'), 400

    # 儲存衣服圖
    img = request.files['image']
    fn2 = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    cloth_path = os.path.join(UPLOAD2, fn2)
    img.save(cloth_path)

    # 呼叫 ComfyUI 之前，記錄現有輸出
    before = {fn for fn in os.listdir(COMFY_OUTPUT) if fn.lower().endswith('.png')}

    # 準備並送出 prompt
    prompt = copy.deepcopy(WORKFLOW_TEMPLATE)
    prompt['3']['inputs']['image'] = last_person['path']
    prompt['4']['inputs']['image'] = cloth_path

    client_id = str(uuid.uuid4())
    payload = {'prompt': prompt, 'client_id': client_id}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(f"http://{COMFY_ADDR}/prompt", data=data)
    try:
        resp = urllib.request.urlopen(req)
        prompt_id = json.loads(resp.read())['prompt_id']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')
        current_app.logger.error('ComfyUI 回 400，body:\n%s', body)
        return jsonify(error=f'呼叫 ComfyUI 失敗：400 Bad Request\n{body}'), 502
    except Exception as e:
        current_app.logger.exception('呼叫 ComfyUI 發生例外：')
        return jsonify(error=f'呼叫 ComfyUI 失敗：{e}'), 502

    # 等待 ComfyUI 完成
    ws = websocket.create_connection(f"ws://{COMFY_ADDR}/ws?clientId={client_id}")
    while True:
        msg = json.loads(ws.recv())
        data_msg = msg.get('data', {})
        if msg.get('type') == 'executing' and data_msg.get('node') is None and data_msg.get('prompt_id') == prompt_id:
            break
    ws.close()

    # 找出新檔並移動
    after = {fn for fn in os.listdir(COMFY_OUTPUT) if fn.lower().endswith('.png')}
    new_files = [os.path.join(COMFY_OUTPUT, fn) for fn in after - before]

    if not new_files:
        current_app.logger.error('執行後沒有在 %s 裡找到任何新 PNG', COMFY_OUTPUT)
        return jsonify(error='找不到本次執行的輸出圖'), 500

    src = max(new_files, key=lambda p: os.path.getmtime(p))
    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    newfn = f'{stamp}.png'
    dst = os.path.join(OUTPUT_DIR, newfn)
    shutil.move(src, dst)
    
   # 回傳前端可用的靜態檔路徑
    #static_rel = os.path.relpath(OUTPUT_DIR, current_app.static_folder)
    #download_url = url_for('static', filename=f'{static_rel}/{newfn}')
    # /outputs/<filename> 
    download_url = url_for('main.serve_output', filename=newfn)
    return jsonify(message='生成完成', download=download_url), 200


