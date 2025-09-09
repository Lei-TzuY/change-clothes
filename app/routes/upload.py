import os
import json
import copy
import time
import uuid
import shutil
import traceback
import urllib.request
import websocket
from flask import Blueprint, request, jsonify, current_app, url_for
from config import UPLOAD1, UPLOAD2, OUTPUT_DIR, COMFY_ADDR, COMFY_OUTPUT

bp = Blueprint('upload', __name__)
last_person = {'path': None}

WF_PATH = os.path.join(os.getcwd(), 'workflow_API.json')
with open(WF_PATH, 'r', encoding='utf-8') as f:
    WORKFLOW_TEMPLATE = json.load(f)


def _json_fail(status, summary, exc=None, extra=None):
    payload = {"error": summary}
    if exc is not None:
        payload["detail"] = str(exc)
        payload["type"] = type(exc).__name__
        payload["traceback"] = traceback.format_exc()
    if extra:
        payload["extra"] = extra
    return jsonify(payload), status


@bp.route('/upload1', methods=['POST'])
def upload1():
    if 'image' not in request.files:
        return jsonify(error='請以 multipart/form-data 上傳 image 檔案', detail={'missing': 'image'}), 400

    img = request.files['image']
    fn = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    save_path = os.path.join(UPLOAD1, fn)
    try:
        img.save(save_path)
    except Exception as e:
        return _json_fail(500, '儲存上傳檔失敗', e, extra={'target': save_path})

    last_person['path'] = save_path
    return jsonify(message='人像圖片已上傳', path=save_path), 200


@bp.route('/upload2', methods=['POST'])
def upload2_and_run_comfy():
    if not last_person['path']:
        return jsonify(error='請先上傳人像'), 400
    if 'image' not in request.files:
        return jsonify(error='請以 multipart/form-data 上傳 image 檔案', detail={'missing': 'image'}), 400

    # 存檔：衣服
    img = request.files['image']
    fn2 = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    cloth_path = os.path.join(UPLOAD2, fn2)
    try:
        img.save(cloth_path)
    except Exception as e:
        return _json_fail(500, '儲存上傳檔失敗', e, extra={'target': cloth_path})

    # 送 ComfyUI 前後比較輸出
    before = {fn for fn in os.listdir(COMFY_OUTPUT) if fn.lower().endswith('.png')}

    # 準備 prompt
    prompt = copy.deepcopy(WORKFLOW_TEMPLATE)
    try:
        prompt['3']['inputs']['image'] = last_person['path']
        prompt['4']['inputs']['image'] = cloth_path
    except Exception:
        pass

    client_id = str(uuid.uuid4())
    payload = {'prompt': prompt, 'client_id': client_id}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(f"http://{COMFY_ADDR}/prompt", data=data)
    try:
        resp = urllib.request.urlopen(req)
        prompt_id = json.loads(resp.read())['prompt_id']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')
        current_app.logger.error('ComfyUI HTTPError %s %s\n%s', getattr(e, 'code', None), getattr(e, 'reason', None), body)
        return jsonify(error='ComfyUI 介面回應錯誤', detail={'code': getattr(e, 'code', None), 'reason': getattr(e, 'reason', None), 'body': body}), 502
    except Exception as e:
        current_app.logger.exception('呼叫 ComfyUI 發生例外')
        return _json_fail(502, '呼叫 ComfyUI 失敗', e, extra={'comfy_addr': COMFY_ADDR})

    # 等待 ComfyUI 執行結束
    last_msg = None
    try:
        ws = websocket.create_connection(f"ws://{COMFY_ADDR}/ws?clientId={client_id}")
        try:
            while True:
                msg = json.loads(ws.recv())
                last_msg = msg
                data_msg = msg.get('data', {})
                if msg.get('type') == 'executing' and data_msg.get('node') is None and data_msg.get('prompt_id') == prompt_id:
                    break
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception as e:
        current_app.logger.exception('WebSocket 連線/等待失敗')
        return _json_fail(502, 'ComfyUI WebSocket 失敗', e, extra={'last_ws_msg': last_msg})

    # 取新輸出
    after = {fn for fn in os.listdir(COMFY_OUTPUT) if fn.lower().endswith('.png')}
    new_files = [os.path.join(COMFY_OUTPUT, fn) for fn in after - before]

    if not new_files:
        current_app.logger.error('未在 %s 找到新的 PNG 輸出', COMFY_OUTPUT)
        return jsonify(error='沒有產生任何輸出圖片', detail={'comfy_output': COMFY_OUTPUT, 'before': list(before), 'after': list(after)}), 500

    src = max(new_files, key=lambda p: os.path.getmtime(p))
    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    newfn = f'{stamp}.png'
    dst = os.path.join(OUTPUT_DIR, newfn)
    try:
        shutil.move(src, dst)
    except Exception as e:
        return _json_fail(500, '搬移輸出檔案失敗', e, extra={'src': src, 'dst': dst})

    download_url = url_for('main.serve_output', filename=newfn)
    return jsonify(message='生成完成', download=download_url), 200

