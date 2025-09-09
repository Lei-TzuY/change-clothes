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


bp = Blueprint("features", __name__)


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


def _run_comfy(prompt_obj):
    before = {f for f in os.listdir(COMFY_OUTPUT) if f.lower().endswith(".png")}

    client_id = str(uuid.uuid4())
    payload = {"prompt": prompt_obj, "client_id": client_id}

    data = json.dumps(payload).encode("utf-8")
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
    return newfn, None


@bp.route("/text2image", methods=["POST"])
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

    newfn, err = _run_comfy(wf)
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
def img2img():
    if "image" not in request.files:
        return jsonify(error="請以上傳 image 檔案 (multipart/form-data)", detail={"missing": "image"}), 400

    img_path = _save_upload(request.files["image"], UPLOAD1)
    prompt_txt = (request.form.get("prompt") or "").strip()
    negative = (request.form.get("negative") or "").strip()

    wf_path = os.path.join(os.getcwd(), "workflows", "圖生圖工作流api.json")
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

    newfn, err = _run_comfy(wf)
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

    newfn, err = _run_comfy(wf)
    if err:
        code, payload = err
        try:
            data = json.loads(payload)
        except Exception:
            data = {"error": payload}
        return jsonify(data), code

    download_url = url_for("main.serve_output", filename=newfn)
    return jsonify(message="生成完成", download=download_url, filename=newfn), 200

