# ===== 匯入需要的工具 =====
import os                          # Python 內建：用來讀取「環境變數」(等下解釋)
from openai import OpenAI          # OpenAI 官方 SDK，但我們會讓它指向本地 Ollama
from dotenv import load_dotenv     # 負責把 .env 檔裡的設定載入成環境變數
from opencc import OpenCC


# ===== 載入設定 =====
# 這行會去專案目錄找 .env 檔，把裡面的設定讀進「環境變數」
# 如果找不到 .env 檔，它不會報錯，只是什麼都不做(這樣設計很安全)
load_dotenv()

# s2twp = 簡體 → 台灣正體(含用語習慣)。建一次重複用，不要每次 new
_cc = OpenCC('s2twp')

def to_traditional(text: str) -> str:
    """把文字中的簡體字強制轉成台灣繁體。
    不依賴模型自律，是程式層級的保證。
    """
    return _cc.convert(text)

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
def ask(prompt: str, system: str = None, model: str = DEFAULT_MODEL) -> str:
    # 先建一個空的對話清單
    messages = []

    # 如果有傳 system(身分/規則設定)，就放在「最前面」第一筆
    # 還記得嗎：模型是文字接龍，放最前面的 system 對整串影響最大
    if system is not None:
        messages.append({"role": "system", "content": system})

    # 再放使用者這次的問題
    messages.append({"role": "user", "content": prompt})

    # 把組好的 messages 送出去
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    
    return to_traditional(response.choices[0].message.content)

class ChatSession:
    """一個會記得對話歷史的對話階段。
    用法：建立一個 ChatSession，反覆呼叫 .send()，它會自動累積上下文。
    """

    def __init__(self, system: str = None, model: str = DEFAULT_MODEL):
        # self.messages 就是「持續累積的對話歷史」，存在這個物件身上
        self.messages = []
        self.model = model

        # 如果有給 system，開場就放進歷史第一筆，整場對話都受它約束
        if system is not None:
            self.messages.append({"role": "system", "content": system})

    def send(self, user_input: str) -> str:
        # 1. 把使用者這句話加進歷史
        self.messages.append({"role": "user", "content": user_input})

        # 2. 把「目前為止的完整歷史」整包送出去
        #    (還記得嗎：模型沒記憶，是我們每次把全部歷史餵回去)
        response = client.chat.completions.create(
            model=self.model,
            messages=self.messages,
        )
        reply = response.choices[0].message.content
        reply = to_traditional(reply)   # ← 強制轉繁，不信任模型

        # 3. 關鍵：把模型的回答也加回歷史(role=assistant)
        #    這樣下一輪 send 時，模型才看得到自己上一輪說過什麼
        self.messages.append({"role": "assistant", "content": reply})

        return reply

# ===== 只有「直接執行這個檔案」時，下面才會跑 =====
# 如果這個檔案是被別的程式 import(引用)，下面就不會自動執行
# 這是 Python 的慣例寫法，讓檔案既能單獨測試、又能被當模組重複使用
# (這正好對應 JD 說的「封裝成可重複使用的功能」)
if __name__ == "__main__":
    expert_system = (
        "你是一位資深製造業品質分析師。"
        "請務必使用繁體中文回答，回答簡潔、條列、聚焦可行動建議。"
    )
    chat = ChatSession(system=expert_system)

    print("第1輪：", chat.send("Q3 某產線不良率從 2% 升到 5%，最該先查什麼？"))
    print("\n第2輪：", chat.send("那如果查下來是某一台機台造成的，下一步呢？"))
    print("\n第3輪：", chat.send("我剛剛問你的第一個問題是什麼？"))