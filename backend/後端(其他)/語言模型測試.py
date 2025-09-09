import requests
import json
import torch
import time
print(torch.cuda.is_available())
print(torch.version.cuda)

def call_ollama_api(input_text):
    curl_url = "http://localhost:11434/api/chat"
    curl_headers = {"Content-Type": "application/json"}
    
    # 這裡與 gguf 設定一致，並使用 FP16 提高推理速度
    curl_data = {
        "model": "sd_model",  # 指定模型名稱
        "messages": [
            {"role": "system", "content": "You are a professional prompt translator for Stable Diffusion. Please translate any Chinese input into English. Do not add extra text, do not explain. Do not change the positions of parentheses or numbers, and always include them exactly as in the original."},
            {"role": "user", "content": input_text}
        ],
        "parameters": {
            "temperature": 0.5,
            "num_ctx": 8192,
            "stop": ["<|system|>", "<|user|>", "<|assistant|>"],
            "fp16": True  # 強制使用 FP16 來加速推理
        }
    }

    try:
        start_time = time.time()  # 記錄開始時間
        response = requests.post(curl_url, json=curl_data, headers=curl_headers)
        response.raise_for_status()
        elapsed_time = time.time() - start_time  # 計算 API 執行時間

        # 逐行解析 JSON，適應流式輸出
        translated_text = ""
        for line in response.text.strip().split("\n"):
            try:
                data = json.loads(line)
                if "message" in data and "content" in data["message"]:
                    translated_text += data["message"]["content"]
            except json.JSONDecodeError as e:
                print(f"JSON Decode Error on line: {line}, Error: {e}")
                continue  # 跳過錯誤行

        return translated_text.strip(), elapsed_time if translated_text else (None, elapsed_time)

    except requests.exceptions.RequestException as e:
        print(f"HTTP Request failed: {e}")
        return None, None

if __name__ == "__main__":

    inputs = [
        "一個男孩跑在海灘上,頭髮:1.5",
        "(藍色短褲):1.2",
        "(黑色頭髮的男生):1.6",
        "(男生帶著眼鏡):1.6",
        "(男生帶著眼鏡:)1.6",
        ""
    ]

  # 啟用 GPU 加速（如果可用）
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    
    for input_text in inputs:
        translated_prompt, execution_time = call_ollama_api(input_text)
        print(f"Input: {input_text}\nTranslated Prompt: {translated_prompt}\nExecution Time: {execution_time:.4f} seconds\n")
