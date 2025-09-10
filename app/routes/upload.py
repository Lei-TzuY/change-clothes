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
from flask_login import current_user

from app.extensions import csrf, limiter
from config import UPLOAD1, UPLOAD2, OUTPUT_DIR, COMFY_ADDR, COMFY_OUTPUT
from backend.comfy import (
    patch_workflow_models,
    get_history_images,
    resolve_history_paths,
    find_new_images_by_scan,
)
from app.models import ImageResult
from app.extensions import db
from app.billing import client_ip, free_remaining, balance, compute_cost, spend


bp = Blueprint('upload', __name__)
csrf.exempt(bp)
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
@limiter.limit("20/minute")
def upload1():
    if 'image' not in request.files:
        return jsonify(error='請以 multipart/form-data 上傳 image 檔案', detail={'missing': 'image'}), 400

    img = request.files['image']
    fn = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    save_path = os.path.join(UPLOAD1, fn)
    try:
        img.save(save_path)
    except Exception as e:
        return _json_fail(500, '寫入上傳檔失敗', e, extra={'target': save_path})

    last_person['path'] = save_path
    return jsonify(message='人像圖片已上傳', path=save_path), 200


@bp.route('/upload2', methods=['POST'])
@limiter.limit("20/minute")
def upload2_and_run_comfy():
    if not last_person['path']:
        return jsonify(error='請先上傳人像'), 400
    if 'image' not in request.files:
        return jsonify(error='請以 multipart/form-data 上傳 image 檔案', detail={'missing': 'image'}), 400

    # 存檔：衣服/素材
    # Credit check before heavy work
    ip = client_ip()
    user_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
    free_left = free_remaining(user_id, ip)
    cost = compute_cost('upload2')
    if free_left <= 0:
        if not user_id:
            return jsonify(error='今日免費次數已用完，請登入並購買點數'), 402
        if balance(user_id) < cost:
            return jsonify(error='點數不足，請先購買', need=cost), 402

    img = request.files['image']
    fn2 = f"{int(time.time())}_{uuid.uuid4().hex}.png"
    cloth_path = os.path.join(UPLOAD2, fn2)
    try:
        img.save(cloth_path)
    except Exception as e:
        return _json_fail(500, '寫入上傳檔失敗', e, extra={'target': cloth_path})

    # 記錄起始狀態
    start_time = time.time() - 0.1
    before = {fn for fn in os.listdir(COMFY_OUTPUT) if fn.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))}

    # 準備 prompt
    prompt = copy.deepcopy(WORKFLOW_TEMPLATE)
    try:
        prompt['3']['inputs']['image'] = last_person['path']
        prompt['4']['inputs']['image'] = cloth_path
    except Exception:
        pass

    # Patch ckpt/vae 為可用值
    try:
        prompt, selected = patch_workflow_models(prompt, COMFY_ADDR)
        if selected.get("ckpt") or selected.get("vae"):
            current_app.logger.info("Using models: ckpt=%s, vae=%s", selected.get("ckpt"), selected.get("vae"))
    except Exception:
        pass

    # 提交 ComfyUI
    client_id = str(uuid.uuid4())
    data = json.dumps({'prompt': prompt, 'client_id': client_id}).encode('utf-8')
    req = urllib.request.Request(f"http://{COMFY_ADDR}/prompt", data=data)
    try:
        resp = urllib.request.urlopen(req)
        prompt_id = json.loads(resp.read())['prompt_id']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')
        current_app.logger.error('ComfyUI HTTPError %s %s\n%s', getattr(e, 'code', None), getattr(e, 'reason', None), body)
        return jsonify(error='ComfyUI 介面回應錯誤', detail={'code': getattr(e, 'code', None), 'reason': getattr(e, 'reason', None), 'body': body}), 502
    except Exception as e:
        current_app.logger.exception('提交 ComfyUI 發生例外')
        return _json_fail(502, '提交 ComfyUI 失敗', e, extra={'comfy_addr': COMFY_ADDR})

    # 等待 ComfyUI 完成
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
        return _json_fail(502, 'ComfyUI WebSocket 錯誤', e, extra={'last_ws_msg': last_msg})

    # 取得輸出：優先使用 history，其次掃描目錄
    hist_imgs = get_history_images(COMFY_ADDR, prompt_id)
    new_files = resolve_history_paths(hist_imgs, COMFY_OUTPUT)
    new_files = [p for p in new_files if os.path.exists(p)]
    if not new_files:
        after = {fn for fn in os.listdir(COMFY_OUTPUT) if fn.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))}
        diff = [os.path.join(COMFY_OUTPUT, fn) for fn in after - before]
        if diff:
            new_files = diff
        else:
            new_files = find_new_images_by_scan(COMFY_OUTPUT, start_time)

    if not new_files:
        current_app.logger.error('未在 %s 偵測到輸出檔案', COMFY_OUTPUT)
        return jsonify(error='沒有產生任何輸出圖片', detail={'comfy_output': COMFY_OUTPUT, 'before': list(before)}), 500

    src = max(new_files, key=lambda p: os.path.getmtime(p))
    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    newfn = f'{stamp}.png'
    dst = os.path.join(OUTPUT_DIR, newfn)
    try:
        shutil.move(src, dst)
    except Exception as e:
        return _json_fail(500, '搬移輸出檔失敗', e, extra={'src': src, 'dst': dst})

    # Record to DB
    try:
        rec = ImageResult(
            filename=newfn,
            kind="upload2",
            source_path=cloth_path,
            output_path=dst,
            user_id=user_id,
            cost_credits=(0.0 if free_left > 0 else cost),
            request_ip=ip,
        )
        db.session.add(rec)
        db.session.commit()
        if free_left <= 0 and user_id:
            spend(user_id, cost, kind='upload2', reference=f'image:{rec.id}')
    except Exception:
        db.session.rollback()

    download_url = url_for('main.serve_output', filename=newfn)
    return jsonify(message='生成完成', download=download_url), 200
