import os
import json
import copy
import time
import uuid
import shutil
import urllib.request
import websocket
import logging

from flask import Blueprint, request, jsonify, current_app

# 跟你原本一樣的設定
from config import UPLOAD1, UPLOAD2, OUTPUT_DIR, COMFY_ADDR, COMFY_OUTPUT

WF_PATH = os.path.join(os.getcwd(), 'workflow_API.json')

bp = Blueprint('upload', __name__)
last_person = {'path': None}

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
    # 1. 確認已上傳人物圖
    if not last_person['path']:
        return jsonify(error='請先上傳人物圖'), 400
    if 'image' not in request.files:
        return jsonify(error='請用 multipart/form-data 並帶 image 欄位'), 400

    # 2. 儲存衣服圖
    img = request.files['image']
    fn2 = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    cloth_path = os.path.join(UPLOAD2, fn2)
    img.save(cloth_path)

    # 3. 執行 ComfyUI 前，先記錄該目錄裡已有的檔名
    before = set(
        fn for fn in os.listdir(COMFY_OUTPUT)
        if fn.lower().endswith('.png')
    )

    # 4. 呼叫 ComfyUI
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

    # 5. 等待 ComfyUI 執行完成（透過 websocket）
    ws = websocket.create_connection(f"ws://{COMFY_ADDR}/ws?clientId={client_id}")
    while True:
        msg = json.loads(ws.recv())
        data_msg = msg.get('data', {})
        # ComfyUI 在所有 node 執行完會送 executing 且 node 為 None
        if msg.get('type') == 'executing' \
           and data_msg.get('node') is None \
           and data_msg.get('prompt_id') == prompt_id:
            break
    ws.close()

    # 6. 執行後，再掃一次，找出新檔
    after = set(
        fn for fn in os.listdir(COMFY_OUTPUT)
        if fn.lower().endswith('.png')
    )
    new_files = [
        os.path.join(COMFY_OUTPUT, fn)
        for fn in (after - before)
    ]

    if not new_files:
        current_app.logger.error('執行後沒有在 %s 裡找到任何新 PNG', COMFY_OUTPUT)
        return jsonify(error='找不到本次執行的輸出圖'), 500

    # 7. 取最新一張並搬到 OUTPUT_DIR
    src = max(new_files, key=lambda p: os.path.getmtime(p))
    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    newfn = f'{stamp}.png'
    dst = os.path.join(OUTPUT_DIR, newfn)
    shutil.move(src, dst)

    return jsonify(message='生成完成', download=f'/return/{newfn}'), 200

