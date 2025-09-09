import requests

def call_gpt4all_api(prompt):
    # GPT4All UI API 端點（假設埠號為 4891）
    url = "http://127.0.0.1:4891/v1/chat/completions"

    # 請確定 'Content-Type' 為 'application/json'
    headers = {
        "Content-Type": "application/json"
    }

    # 定義與 OpenAI ChatCompletion 相容的 JSON 結構
    payload = {
        "model": "DeepSeek-Coder-V2-Lite-Instruct-Q8_0.gguf",  # 模型名稱請與 GPT4All UI 裡載入的相同
        "messages": [
            {"role": "system", "content": "你是一個專業的 Python 程式設計師。"},
            {"role": "user", "content": prompt}
        ],
        # 其他參數可自由調整
        "max_tokens": 256,
        "temperature": 0.7
    }

    # 將 payload 以 POST 方式發送到 GPT4All UI
    response = requests.post(url, headers=headers, json=payload)

    # 解析並回傳結果（JSON 格式）
    return response.json()

if __name__ == "__main__":
    user_input = "請用 Python 幫我實作一個讀取 CSV 檔案的範例"
    result = call_gpt4all_api(user_input)
    
    # 印出原始 JSON 內容
    print(result)
    
    # 如果要取得模型回應的文字，可以從 result["choices"][0]["message"]["content"] 中取用
    if "choices" in result and len(result["choices"]) > 0:
        print("\nAI 回應內容：")
        print(result["choices"][0]["message"]["content"])
