import json
import os
import time
from typing import Dict, List, Optional, Tuple

import requests
from flask import current_app, session, has_request_context


def _fetch_object_info(comfy_addr: str) -> Dict:
    url = f"http://{comfy_addr}/object_info"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    return r.json()


def _extract_choices(obj_info: Dict, node_type: str, field: str) -> List[str]:
    try:
        # ComfyUI returns input metadata where enum-style fields are returned as [choices, extra_dict]
        return list(obj_info[node_type]["input"]["required"][field][0])
    except Exception:
        return []


def _normalize(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def pick_available(preferred: Optional[str], choices: List[str]) -> Optional[str]:
    """
    Choose a reasonable checkpoint/VAE name from choices.
    Preference order:
    1) Exact match to preferred
    2) First candidate after filtering out obviously-non-SD names (heuristics)
    3) First item in choices
    Heuristics can be tuned via env vars:
      CKPT_INCLUDE_KEYWORDS (comma-separated)
      CKPT_EXCLUDE_KEYWORDS (comma-separated)
    """
    if preferred and preferred in choices:
        return preferred

    if not choices:
        return preferred

    inc = [k for k in _normalize(os.getenv("CKPT_INCLUDE_KEYWORDS", "meinamix,sdxl,sd,realistic,rev,juggernaut,dreamshaper,anything")).split(",") if k]
    exc = [k for k in _normalize(os.getenv("CKPT_EXCLUDE_KEYWORDS", "mat_,video,hyvideo,animate")).split(",") if k]

    # Filter out excluded keywords
    filtered = [c for c in choices if not any(k in _normalize(c) for k in exc)]

    # Prefer include keywords
    for kw in inc:
        for c in filtered:
            if kw in _normalize(c):
                return c

    # Fallbacks
    if filtered:
        return filtered[0]
    return choices[0]


def patch_workflow_models(wf: Dict, comfy_addr: str) -> Tuple[Dict, Dict[str, Optional[str]]]:
    """
    Ensure workflow uses available ckpt/vae names.
    - Tries to keep config preferred names (CKPT_NAME/VAE_NAME)
    - Falls back to first available reported by ComfyUI /object_info
    """
    cfg = current_app.config if current_app else {}
    preferred_ckpt = None
    preferred_vae = None
    # Prefer per-session selections if available
    try:
        if has_request_context():
            preferred_ckpt = session.get("CKPT_NAME")
            preferred_vae = session.get("VAE_NAME")
    except Exception:
        pass
    # Fallback to app config
    if not preferred_ckpt:
        preferred_ckpt = cfg.get("CKPT_NAME")
    if not preferred_vae:
        preferred_vae = cfg.get("VAE_NAME")

    choices = {"ckpt": [], "vae": []}
    try:
        obj_info = _fetch_object_info(comfy_addr)
        choices["ckpt"] = _extract_choices(obj_info, "CheckpointLoaderSimple", "ckpt_name")
        choices["vae"] = _extract_choices(obj_info, "VAELoader", "vae_name")
    except Exception:
        # Swallow; we'll fall back to preferred names if provided
        pass

    selected = {
        "ckpt": pick_available(preferred_ckpt, choices["ckpt"]),
        "vae": pick_available(preferred_vae, choices["vae"]),
    }

    # Traverse nodes and patch
    try:
        for nid, node in wf.items():
            if not isinstance(node, dict):
                continue
            ctype = node.get("class_type")
            inputs = node.get("inputs", {})
            if ctype == "CheckpointLoaderSimple" and selected["ckpt"]:
                inputs["ckpt_name"] = selected["ckpt"]
            elif ctype == "VAELoader" and selected["vae"]:
                inputs["vae_name"] = selected["vae"]
    except Exception:
        pass

    return wf, selected


def get_model_options(comfy_addr: str) -> Dict[str, Optional[List[str]] | Optional[str]]:
    """
    Return available ckpt/vae choices from ComfyUI and recommended defaults.
    - recommended_* will try to honor session/config preference if present and valid,
      otherwise fall back to a heuristic pick from available choices.
    - selected_* reflects the current session-selected value if set; otherwise None.
    """
    cfg = current_app.config if current_app else {}
    try:
        sess_ckpt = session.get("CKPT_NAME") if has_request_context() else None
        sess_vae = session.get("VAE_NAME") if has_request_context() else None
    except Exception:
        sess_ckpt = None
        sess_vae = None

    pref_ckpt = sess_ckpt or cfg.get("CKPT_NAME")
    pref_vae = sess_vae or cfg.get("VAE_NAME")

    ckpt_choices: List[str] = []
    vae_choices: List[str] = []
    try:
        info = _fetch_object_info(comfy_addr)
        ckpt_choices = _extract_choices(info, "CheckpointLoaderSimple", "ckpt_name")
        vae_choices = _extract_choices(info, "VAELoader", "vae_name")
    except Exception:
        # ComfyUI might be offline; leave choices empty
        pass

    rec_ckpt = pick_available(pref_ckpt, ckpt_choices) if ckpt_choices else (pref_ckpt or None)
    rec_vae = pick_available(pref_vae, vae_choices) if vae_choices else (pref_vae or None)

    return {
        "ckpt_choices": ckpt_choices,
        "vae_choices": vae_choices,
        "recommended_ckpt": rec_ckpt,
        "recommended_vae": rec_vae,
        "selected_ckpt": sess_ckpt,
        "selected_vae": sess_vae,
    }


def get_history_images(comfy_addr: str, prompt_id: str) -> List[Dict[str, str]]:
    """Query ComfyUI /history/<prompt_id> and extract image records.
    Returns list of dicts: {filename, subfolder, type}
    """
    try:
        url = f"http://{comfy_addr}/history/{prompt_id}"
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        # Structure: {prompt_id: {outputs: {node_id: {images: [...]}}}}
        result: List[Dict[str, str]] = []
        node_outputs = data.get(prompt_id, {}).get("outputs", {})
        for _nid, out in node_outputs.items():
            for img in out.get("images", []) or []:
                if isinstance(img, dict) and img.get("filename"):
                    result.append({
                        "filename": img.get("filename"),
                        "subfolder": img.get("subfolder", ""),
                        "type": img.get("type", "")
                    })
        return result
    except Exception:
        return []


def resolve_history_paths(images: List[Dict[str, str]], base_output: str) -> List[str]:
    paths: List[str] = []
    for img in images:
        fn = img.get("filename")
        sub = img.get("subfolder") or ""
        if not fn:
            continue
        path = os.path.join(base_output, sub, fn)
        paths.append(path)
    return paths


def find_new_images_by_scan(output_dir: str, start_time: float) -> List[str]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    out: List[str] = []
    try:
        for root, _dirs, files in os.walk(output_dir):
            for f in files:
                if os.path.splitext(f)[1].lower() in exts:
                    p = os.path.join(root, f)
                    try:
                        if os.path.getmtime(p) >= start_time:
                            out.append(p)
                    except OSError:
                        pass
    except Exception:
        pass
    # Sort by mtime desc
    out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out
