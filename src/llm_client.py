# ===== 匯入需要的工具 =====
import os                          # Python 內建：用來讀取「環境變數」(等下解釋)
from openai import OpenAI          # OpenAI 官方 SDK，但我們會讓它指向本地 Ollama
from dotenv import load_dotenv     # 負責把 .env 檔裡的設定載入成環境變數

# ===== 載入設定 =====
# 這行會去專案目錄找 .env 檔，把裡面的設定讀進「環境變數」
# 如果找不到 .env 檔，它不會報錯，只是什麼都不做(這樣設計很安全)
load_dotenv()

# ===== 建立連線到 LLM 的客戶端 =====
client = OpenAI(
    # os.getenv("名字", "預設值") 的意思是：
    #   去環境變數找叫 LLM_BASE_URL 的設定，
    #   找到就用找到的值；沒找到就用後面那個預設值(本地 Ollama 網址)
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),

    # 同理，找 LLM_API_KEY；本地 Ollama 不檢查 key，但 SDK 規定一定要給一個值
    api_key=os.getenv("LLM_API_KEY", "ollama"),
)

# 預設要用哪個模型，一樣可被環境變數覆蓋；沒設定就用 3b(小、快，適合開發測試)
DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")


# ===== 定義一個可重複使用的函式：問問題、拿回答 =====
# prompt: 你要問的問題(字串)
# model: 要用哪個模型，沒指定就用上面的 DEFAULT_MODEL
# -> str 表示這個函式會回傳一個字串
def ask(prompt: str, model: str = DEFAULT_MODEL) -> str:
    # 呼叫 LLM。messages 是「對話內容」，下面第三部分會詳細解釋它的結構
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    # 模型回傳的資料結構有很多層，這行是把「第一個回答的文字內容」取出來
    return response.choices[0].message.content


# ===== 只有「直接執行這個檔案」時，下面才會跑 =====
# 如果這個檔案是被別的程式 import(引用)，下面就不會自動執行
# 這是 Python 的慣例寫法，讓檔案既能單獨測試、又能被當模組重複使用
# (這正好對應 JD 說的「封裝成可重複使用的功能」)
if __name__ == "__main__":
    print(ask("用一句話解釋什麼是『不良率』"))