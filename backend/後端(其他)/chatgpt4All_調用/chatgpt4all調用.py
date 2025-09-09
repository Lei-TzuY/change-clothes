from gpt4all import GPT4All

# 模型檔名（請確認與實際檔案一致）
model_name = "DeepSeek-Coder-V2-Lite-Instruct-Q8_0.gguf"

# 模型所在的資料夾路徑，請使用原始字串或雙反斜線表示路徑
model_path = r"C:\Users\User\Desktop\deepseek"

# 建立 GPT4All 物件，若找不到模型則不允許下載
gptj = GPT4All(model_name=model_name, model_path=model_path, allow_download=False)

# 系統指令與使用者請求
system_instruction = """
你是一個專業的 Python 程式設計師，請用清晰且易於理解的方式回應所有問題，並提供註解。
請確保代碼能直接運行，並遵循最佳實踐。
"""
prompt_text = "請用 Python 幫我實作一個讀取 CSV 檔案的範例"

# 將系統指令與 prompt 組合在一起
full_prompt = system_instruction + "\n" + prompt_text

# 使用 generate() 方法取得模型回應
response = gptj.generate(prompt=full_prompt)

# 輸出回應
print(response)

# 若有需要關閉資源，可以檢查是否有相應的 close() 方法
if hasattr(gptj, "close"):
    gptj.close()
