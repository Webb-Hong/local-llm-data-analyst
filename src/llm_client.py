# ===== 匯入需要的工具 =====
import os
from urllib import response                          # Python 內建：用來讀取「環境變數」(等下解釋)
from openai import OpenAI          # OpenAI 官方 SDK，但我們會讓它指向本地 Ollama
from dotenv import load_dotenv     # 負責把 .env 檔裡的設定載入成環境變數
from opencc import OpenCC
import json                        # Python 內建：用來處理 JSON 格式的字串和物件
from pydantic import BaseModel, field_validator
from typing import List

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
    
def analyze(situation: str, model: str = DEFAULT_MODEL) -> str:
    """給一個製造分析情境，要求模型回傳結構化 JSON 字串。
    這一版先只負責『要到 JSON』，驗證留到下一個任務。
    """
    system = (
        "你是資深製造業品質分析師。"
        "你必須只輸出一個 JSON 物件，不要有任何其他文字、不要 markdown 標記。"
        "JSON 必須包含這四個鍵："
        "可能原因(字串陣列)、"
        "嚴重程度(只能是 高/中/低 三者其一的字串)、"
        "建議行動(字串陣列)、"
        "需要補充的資訊(字串陣列)。"
        "全部使用繁體中文。"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": situation},
        ],
        # 這個參數要求模型輸出合法 JSON 格式(Ollama / OpenAI 都支援)
        response_format={"type": "json_object"},
    )

    return response.choices[0].message.content

class AnalysisResult(BaseModel):
    """定義『一份合格的分析結果』必須長什麼樣。
    模型輸出只要不符合這裡的規則，建立這個物件時就會自動報錯。
    """
    可能原因: List[str]
    嚴重程度: str
    建議行動: List[str]
    需要補充的資訊: List[str]

    @field_validator("嚴重程度")
    @classmethod
    def 嚴重程度只能三選一(cls, v):
        if v not in ("高", "中", "低"):
            raise ValueError(f"嚴重程度必須是 高/中/低，但收到：{v}")
        return v

    @field_validator("可能原因", "建議行動")
    @classmethod
    def 不可以是空陣列(cls, v):
        if len(v) == 0:
            raise ValueError("這個欄位不能是空陣列")
        return v
    
def analyze_validated(situation: str, max_retries: int = 3, model: str = DEFAULT_MODEL) -> AnalysisResult:
    """要求模型輸出分析 JSON，並用 Pydantic 嚴格驗證。
    驗證失敗就重試，最多 max_retries 次；全部失敗則明確拋錯。
    """
    system = (
        "你是資深製造業品質分析師。只輸出一個 JSON 物件，無其他文字、無 markdown。"
        "鍵：可能原因(字串陣列)、嚴重程度(只能 高/中/低)、"
        "建議行動(字串陣列)、需要補充的資訊(字串陣列)。全部繁體中文。"
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        raw = ""
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": situation},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content

            data = json.loads(raw)                 # 第一關：格式驗證(確定性)
            result = AnalysisResult(**data)        # 第二關：內容驗證(Pydantic)
            print(f"[第 {attempt} 次嘗試成功]")
            return result                          # 兩關都過才回傳

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            print(f"[第 {attempt} 次失敗] {type(e).__name__}: {e}")
            print(f"   模型原始輸出：{raw[:200]}")
            continue                               # 失敗就再試一次

    # 全部重試用完還是失敗 → 不吞錯，明確讓呼叫者知道
    raise RuntimeError(f"連續 {max_retries} 次都無法取得合格結果，最後錯誤：{last_error}")

# ===== 只有「直接執行這個檔案」時，下面才會跑 =====
# 如果這個檔案是被別的程式 import(引用)，下面就不會自動執行
# 這是 Python 的慣例寫法，讓檔案既能單獨測試、又能被當模組重複使用
# (這正好對應 JD 說的「封裝成可重複使用的功能」)
if __name__ == "__main__":
    result = analyze_validated(
        "Q3 SMT 產線不良率從 2% 升到 5%，缺陷多為錫橋(solder bridge)。"
    )
    print("嚴重程度：", result.嚴重程度)
    print("可能原因：", result.可能原因)
    print("建議行動：", result.建議行動)