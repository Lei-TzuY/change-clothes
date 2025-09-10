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
from app.extensions import csrf, limiter

from config import UPLOAD1, UPLOAD2, OUTPUT_DIR, COMFY_ADDR, COMFY_OUTPUT
from backend.comfy import patch_workflow_models, get_model_options
from app.models import ImageResult
from app.extensions import db
from flask_login import current_user
from app.billing import client_ip, free_remaining, balance, compute_cost, spend


bp = Blueprint("features", __name__)
csrf.exempt(bp)


def _save_upload(file_storage, target_dir):
    os.makedirs(target_dir, exist_ok=True)
    _, ext = os.path.splitext(file_storage.filename or "")
    if not ext:
        ext = ".png"
    fn = f"{int(time.time())}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(target_dir, fn)
    file_storage.save(path)
    return path


def _json_fail(status, summary, exc=None, extra=None):
    payload = {"error": summary}
    if exc is not None:
        payload["detail"] = str(exc)
        payload["type"] = type(exc).__name__
        payload["traceback"] = traceback.format_exc()
    if extra:
        payload["extra"] = extra
    return jsonify(payload), status


@bp.get("/models/options")
def model_options():
    """Expose available checkpoint/VAE choices and recommended defaults.
    Useful for building dropdowns on the client.
    """
    try:
        opts = get_model_options(current_app.config.get("COMFY_ADDR", "127.0.0.1:8188"))
        return jsonify(opts), 200
    except Exception as e:
        return jsonify(error="failed to fetch model options", detail=str(e)), 500


def _run_comfy(prompt_obj, kind=None, billing=None):
    before = {f for f in os.listdir(COMFY_OUTPUT) if f.lower().endswith(".png")}

    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt_obj, "client_id": client_id}

    # Patch models to current ComfyUI availability (ckpt/vae)
    try:
        prompt_obj, selected = patch_workflow_models(prompt_obj, COMFY_ADDR)
        current_app.logger.info("Using models: ckpt=%s, vae=%s", selected.get("ckpt"), selected.get("vae"))
    except Exception:
        pass

    data = json.dumps({"prompt": prompt_obj, "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(f"http://{COMFY_ADDR}/prompt", data=data)

    try:
        resp = urllib.request.urlopen(req)
        prompt_id = json.loads(resp.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            body = None
        current_app.logger.error("ComfyUI HTTPError %s %s\n%s", getattr(e, 'code', None), getattr(e, 'reason', None), body)
        err = {
            "code": getattr(e, "code", None),
            "reason": getattr(e, "reason", None),
            "body": body,
            "comfy_addr": COMFY_ADDR,
        }
        return None, (502, json.dumps({"error": "ComfyUI 介面回應錯誤", "detail": err}, ensure_ascii=False))
    except Exception as e:
        current_app.logger.exception("ComfyUI 發送請求時發生例外")
        err = {"exception": str(e), "traceback": traceback.format_exc(), "comfy_addr": COMFY_ADDR}
        return None, (502, json.dumps({"error": "ComfyUI 介面異常", "detail": err}, ensure_ascii=False))

    # Wait on websocket for completion
    last_msg = None
    try:
        ws = websocket.create_connection(f"ws://{COMFY_ADDR}/ws?clientId={client_id}")
        try:
            while True:
                msg = json.loads(ws.recv())
                last_msg = msg
                data_msg = msg.get("data", {})
                if (
                    msg.get("type") == "executing"
                    and data_msg.get("node") is None
                    and data_msg.get("prompt_id") == prompt_id
                ):
                    break
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception as e:
        current_app.logger.exception("WebSocket 等待執行完成時發生例外")
        err = {"exception": str(e), "traceback": traceback.format_exc(), "last_ws_msg": last_msg}
        return None, (502, json.dumps({"error": "ComfyUI WebSocket 連線/等待失敗", "detail": err}, ensure_ascii=False))

    # Find new image(s)
    after = {f for f in os.listdir(COMFY_OUTPUT) if f.lower().endswith(".png")}
    new_files = [os.path.join(COMFY_OUTPUT, f) for f in after - before]
    if not new_files:
        current_app.logger.error("未在 %s 找到新的 PNG 輸出", COMFY_OUTPUT)
        err = {"comfy_output": COMFY_OUTPUT, "before": list(before), "after": list(after)}
        return None, (500, json.dumps({"error": "沒有產生任何輸出圖片", "detail": err}, ensure_ascii=False))

    src = max(new_files, key=lambda p: os.path.getmtime(p))
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    newfn = f"{stamp}.png"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    dst = os.path.join(OUTPUT_DIR, newfn)
    shutil.move(src, dst)
    try:
        user_id = None
        req_ip = None
        cost = 0.0
        use_free = True
        if isinstance(billing, dict):
            user_id = billing.get('user_id')
            req_ip = billing.get('ip')
            use_free = bool(billing.get('use_free'))
            cost = 0.0 if use_free else float(billing.get('cost') or 0.0)
        else:
            user_id = (current_user.id if getattr(current_user, 'is_authenticated', False) else None)

        rec = ImageResult(
            filename=newfn,
            kind=kind or "unknown",
            source_path=None,
            output_path=dst,
            user_id=user_id,
            cost_credits=cost,
            request_ip=req_ip,
        )
        db.session.add(rec)
        db.session.commit()
        if not use_free and user_id:
            spend(int(user_id), float(cost), kind=kind or 'unknown', reference=f'image:{rec.id}')
    except Exception:
        db.session.rollback()
    return newfn, None


@bp.route("/text2image", methods=["POST"])
@limiter.limit("30/minute")
def text2image():
    prompt_txt = (request.form.get("prompt") or "").strip()
    if not prompt_txt:
        return jsonify(error="請提供 prompt", detail={"missing": "prompt"}), 400

    negative = (request.form.get("negative") or "").strip()

    wf_path = os.path.join(os.getcwd(), "workflows", "文生圖工作流api.json")
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
    except Exception as e:
        return _json_fail(500, "讀取工作流失敗", e)

    wf = copy.deepcopy(wf)

    # Optional: allow client to specify an alternative workflow file path
    alt_path = (request.form.get("workflow_path") or "").strip()
    if alt_path:
        try:
            if os.path.isabs(alt_path) and os.path.exists(alt_path):
                with open(alt_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
            else:
                alt_full = os.path.join(os.getcwd(), alt_path)
                if os.path.exists(alt_full):
                    with open(alt_full, "r", encoding="utf-8") as f:
                        wf = json.load(f)
        except Exception:
            pass

    # Optional overrides: ckpt / vae / workflow path inputs
    try:
        ckpt_override = (request.form.get("ckpt_name") or "").strip()
        if ckpt_override:
            for _nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple":
                    node.setdefault("inputs", {})["ckpt_name"] = ckpt_override
        vae_override = (request.form.get("vae_name") or "").strip()
        if vae_override:
            for _nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "VAELoader":
                    node.setdefault("inputs", {})["vae_name"] = vae_override
    except Exception:
        pass

    # Patch prompt/negative
    try:
        wf["2"]["inputs"]["text"] = prompt_txt
        wf["3"]["inputs"]["text"] = negative
    except Exception:
        pass

    # Optional sampler params
    sampler = wf.get("4", {}).get("inputs", {})

    def _maybe_num(v):
        if v is None or v == "":
            return None
        try:
            if "." in str(v):
                return float(v)
            return int(v)
        except Exception:
            return v

    for key in ("seed", "steps", "cfg"):
        val = _maybe_num(request.form.get(key))
        if val is not None and isinstance(sampler, dict):
            sampler[key] = val
    for key in ("sampler_name", "scheduler"):
        val = request.form.get(key)
        if val:
            sampler[key] = val

    # Optional size on EmptyLatentImage (commonly node 15)
    width = _maybe_num(request.form.get("width"))
    height = _maybe_num(request.form.get("height"))
    try:
        if width:
            wf["15"]["inputs"]["width"] = width
        if height:
            wf["15"]["inputs"]["height"] = height
    except Exception:
        pass

    # Billing check
    ip = client_ip()
    user_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
    steps_val = sampler.get('steps') if isinstance(sampler, dict) else None
    cost = compute_cost('text2image', width=width, height=height, steps=steps_val)
    free_left = free_remaining(user_id, ip)
    if free_left <= 0:
        if not user_id:
            return jsonify(error='今日免費次數已用完，請登入並購買點數'), 402
        if balance(user_id) < cost:
            return jsonify(error='點數不足，請先購買', need=cost), 402

    newfn, err = _run_comfy(wf, kind="text2image", billing={
        'user_id': user_id,
        'ip': ip,
        'cost': cost,
        'use_free': free_left > 0,
    })
    if err:
        code, payload = err
        try:
            data = json.loads(payload)
        except Exception:
            data = {"error": payload}
        return jsonify(data), code

    download_url = url_for("main.serve_output", filename=newfn)
    return jsonify(message="生成完成", download=download_url, filename=newfn), 200


@bp.route("/img2img", methods=["POST"])
@limiter.limit("30/minute")
def img2img():
    if "image" not in request.files:
        return jsonify(error="請以上傳 image 檔案 (multipart/form-data)", detail={"missing": "image"}), 400

    img_path = _save_upload(request.files["image"], UPLOAD1)
    prompt_txt = (request.form.get("prompt") or "").strip()
    negative = (request.form.get("negative") or "").strip()

    wf_path = os.path.join(os.getcwd(), "workflows", "目前的服務", "圖生圖工作流api.json")
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
    except Exception as e:
        return _json_fail(500, "讀取工作流失敗", e)

    wf = copy.deepcopy(wf)

    # Prompts
    try:
        wf["2"]["inputs"]["text"] = prompt_txt
        wf["3"]["inputs"]["text"] = negative
    except Exception:
        pass

    # Set image input
    patched = False
    # Prefer LoadImage node (id 10 in provided workflow)
    try:
        if "10" in wf and isinstance(wf["10"], dict) and "inputs" in wf["10"] and "image" in wf["10"]["inputs"]:
            wf["10"]["inputs"]["image"] = img_path
            patched = True
    except Exception:
        pass
    try:
        if "17" in wf and "inputs" in wf["17"]:
            if "image" in wf["17"]["inputs"]:
                wf["17"]["inputs"]["image"] = img_path
                patched = True
    except Exception:
        pass
    if not patched:
        for nid in ("30", "47", "50"):
            if nid in wf and isinstance(wf[nid], dict) and "inputs" in wf[nid]:
                if "image_path" in wf[nid]["inputs"]:
                    wf[nid]["inputs"]["image_path"] = img_path
                    patched = True
                    break

    # Sampler params
    sampler = wf.get("4", {}).get("inputs", {})

    def _maybe_num(v):
        if v is None or v == "":
            return None
        try:
            if "." in str(v):
                return float(v)
            return int(v)
        except Exception:
            return v

    for key in ("seed", "steps", "cfg", "denoise"):
        val = _maybe_num(request.form.get(key))
        if val is not None and isinstance(sampler, dict):
            sampler[key] = val
    # Allow sampler_name / scheduler to be overridden by user
    for key in ("sampler_name", "scheduler"):
        sval = request.form.get(key)
        if sval and isinstance(sampler, dict):
            sampler[key] = sval

    # Optional overrides: ckpt / vae
    try:
        ckpt_override = (request.form.get("ckpt_name") or "").strip()
        if ckpt_override:
            for _nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple":
                    node.setdefault("inputs", {})["ckpt_name"] = ckpt_override
        vae_override = (request.form.get("vae_name") or "").strip()
        if vae_override:
            for _nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "VAELoader":
                    node.setdefault("inputs", {})["vae_name"] = vae_override
    except Exception:
        pass

    # Optional: override LatentUpscale width/height if node 14 exists
    w_override = _maybe_num(request.form.get("width"))
    h_override = _maybe_num(request.form.get("height"))
    try:
        if "14" in wf and isinstance(wf["14"], dict) and "inputs" in wf["14"]:
            if w_override:
                wf["14"]["inputs"]["width"] = int(w_override)
            if h_override:
                wf["14"]["inputs"]["height"] = int(h_override)
    except Exception:
        pass

    # Billing check
    ip = client_ip()
    user_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
    steps_val = sampler.get('steps') if isinstance(sampler, dict) else None
    denoise_val = sampler.get('denoise') if isinstance(sampler, dict) else None
    cost = compute_cost('img2img', steps=steps_val, denoise=denoise_val)
    free_left = free_remaining(user_id, ip)
    if free_left <= 0:
        if not user_id:
            return jsonify(error='今日免費次數已用完，請登入並購買點數'), 402
        if balance(user_id) < cost:
            return jsonify(error='點數不足，請先購買', need=cost), 402

    newfn, err = _run_comfy(wf, kind="img2img", billing={
        'user_id': user_id,
        'ip': ip,
        'cost': cost,
        'use_free': free_left > 0,
    })
    if err:
        code, payload = err
        try:
            data = json.loads(payload)
        except Exception:
            data = {"error": payload}
        return jsonify(data), code

    download_url = url_for("main.serve_output", filename=newfn)
    return jsonify(message="生成完成", download=download_url, filename=newfn), 200


@bp.route("/inpaint", methods=["POST"])
@limiter.limit("30/minute")
def inpaint():
    if "image" not in request.files or "mask" not in request.files:
        missing = [k for k in ("image", "mask") if k not in request.files]
        return jsonify(error="請上傳 image 與 mask 檔案", detail={"missing": missing}), 400

    base_img = _save_upload(request.files["image"], UPLOAD1)
    mask_img = _save_upload(request.files["mask"], UPLOAD2)
    prompt_txt = (request.form.get("prompt") or "").strip()
    negative = (request.form.get("negative") or "").strip()

    wf_path = os.path.join(os.getcwd(), "workflows", "圖生圖工作流局部重繪api.json")
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
    except Exception as e:
        return _json_fail(500, "讀取工作流失敗", e)

    wf = copy.deepcopy(wf)

    try:
        wf["2"]["inputs"]["text"] = prompt_txt
        wf["3"]["inputs"]["text"] = negative
    except Exception:
        pass

    try:
        if "28" in wf and "inputs" in wf["28"] and "image_path" in wf["28"]["inputs"]:
            wf["28"]["inputs"]["image_path"] = base_img
    except Exception:
        pass
    try:
        if "29" in wf and "inputs" in wf["29"] and "image_path" in wf["29"]["inputs"]:
            wf["29"]["inputs"]["image_path"] = mask_img
    except Exception:
        pass

    # Optional overrides: ckpt / vae
    try:
        ckpt_override = (request.form.get("ckpt_name") or "").strip()
        if ckpt_override:
            for _nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple":
                    node.setdefault("inputs", {})["ckpt_name"] = ckpt_override
        vae_override = (request.form.get("vae_name") or "").strip()
        if vae_override:
            for _nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "VAELoader":
                    node.setdefault("inputs", {})["vae_name"] = vae_override
    except Exception:
        pass

    # Billing check
    ip = client_ip()
    user_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
    cost = compute_cost('inpaint')
    free_left = free_remaining(user_id, ip)
    if free_left <= 0:
        if not user_id:
            return jsonify(error='今日免費次數已用完，請登入並購買點數'), 402
        if balance(user_id) < cost:
            return jsonify(error='點數不足，請先購買', need=cost), 402

    newfn, err = _run_comfy(wf, kind="inpaint", billing={
        'user_id': user_id,
        'ip': ip,
        'cost': cost,
        'use_free': free_left > 0,
    })
    if err:
        code, payload = err
        try:
            data = json.loads(payload)
        except Exception:
            data = {"error": payload}
        return jsonify(data), code

    download_url = url_for("main.serve_output", filename=newfn)
    return jsonify(message="生成完成", download=download_url, filename=newfn), 200

