import json
import uuid
import urllib.request
import websocket
import logging
import os

class ComfyClient:
    def __init__(self, addr, output_dir):
        self.addr = addr
        self.output_dir = output_dir
        self.logger = logging.getLogger(__name__)

    def send_prompt(self, workflow):
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"http://{self.addr}/prompt", data=data)
        self.logger.debug(">>> ComfyUI payload:\n%s", json.dumps(payload, ensure_ascii=False))
        resp = urllib.request.urlopen(req)
        prompt_id = json.loads(resp.read())["prompt_id"]
        return prompt_id, client_id

    def wait_done(self, client_id, prompt_id):
        ws = websocket.create_connection(f"ws://{self.addr}/ws?clientId={client_id}")
        while True:
            msg = json.loads(ws.recv())
            data = msg.get("data", {})
            if msg.get("type") == "executing" \
               and data.get("node") is None \
               and data.get("prompt_id") == prompt_id:
                break
        ws.close()

    def fetch_latest(self, since_ts):
        new_files = []
        for fn in os.listdir(self.output_dir):
            if not fn.lower().endswith(".png"):
                continue
            full = os.path.join(self.output_dir, fn)
            if os.path.getctime(full) >= since_ts:
                new_files.append(full)
        if not new_files:
            raise FileNotFoundError("找不到本次執行的輸出圖")
        return max(new_files, key=lambda p: os.path.getctime(p))

