"""FastAPI 服務：把製造分析引擎包成 RESTful API。"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai
from typing import List, Optional
from pydantic import BaseModel, field_validator

from src.analyzer import get_line_defect_rates, build_situation
from src.llm_client import (
    analyze_validated,
    AnalysisResult,
    analyze_dataset,
    DataInsight,
    client,            # 補:LLM 用的 OpenAI client
    to_traditional,    # 補:opencc 轉繁體
    DEFAULT_MODEL,     # 補:預設模型名稱
)
from fastapi import UploadFile, File
from src.data_explorer import load_csv_from_bytes, explore_dataframe, build_data_situation
from src.vector_retriever import retrieve

import logging

# 設定一個 logger,用來把錯誤記錄到伺服器端(不是回給使用者)
logging.basicConfig(level=logging.INFO)        # 設門檻=INFO
logger = logging.getLogger(__name__)           # 建一個以模組名為名的 logger

app = FastAPI(title="製造分析 API", version="0.2.0")


# ===== 輸入模型：定義「一個合法的分析請求」長什麼樣 =====
class DiagnosisRequest(BaseModel):
    line_id: str   # 使用者必須提供要分析哪條產線
    
# ===== 多輪對話的請求/回應模型 =====
class ChatMessage(BaseModel):
    """單筆對話訊息,結構與 OpenAI/Ollama API 一致。"""
    role: str          # "system" / "user" / "assistant"
    content: str

    @field_validator("role")
    @classmethod
    def role必須是三種之一(cls, v):
        if v not in ("system", "user", "assistant"):
            raise ValueError(f"role 必須是 system/user/assistant,但收到:{v}")
        return v


class ChatRequest(BaseModel):
    """多輪對話請求。
    - messages: 前端維護的完整對話歷史(API 不記憶,完全靠這個)
    - data_profile_text: 第 1 輪時帶上資料情境(由前端的 build_data_situation 產生)
    - auto_compress: 是否在歷史過長時自動摘要壓縮
    """
    messages: List[ChatMessage]
    data_profile_text: Optional[str] = None
    auto_compress: bool = True

    @field_validator("messages")
    @classmethod
    def messages不可為空(cls, v):
        if len(v) == 0:
            raise ValueError("messages 不能為空,至少要有一筆 user 訊息")
        return v


class ChatResponse(BaseModel):
    """多輪對話回應。回傳『更新後的完整訊息列表』,前端直接覆蓋。"""
    updated_messages: List[ChatMessage]    # 包含這輪 user + assistant 的完整新歷史
    was_compressed: bool                   # 這次是否觸發了歷史壓縮


# @app.get("/")
# def read_root():
#     return {"message": "製造分析 API 運行中", "status": "ok"}

@app.get("/")
def read_root():
    return {"message": "製造分析 API 運行中 v2", "status": "ok"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# ===== GET：列出所有產線的不良率(讀取,所以 GET) =====
@app.get("/lines")
def list_lines():
    return get_line_defect_rates()


# ===== POST：對指定產線做一次 LLM 分析(觸發動作,所以 POST) =====
# response_model=AnalysisResult →
#   FastAPI 會用你階段 2 的 AnalysisResult 驗證「回應」結構,
#   並自動轉成 JSON、自動寫進 API 文件。輸入輸出兩端都有確定性關卡。
@app.post("/diagnosis", response_model=AnalysisResult)
def diagnose(request: DiagnosisRequest):
    valid_lines = {r["line_id"] for r in get_line_defect_rates()}

    # 失敗類型一:資源不存在 → 404(這段你已有,保留)
    if request.line_id not in valid_lines:
        raise HTTPException(
            status_code=404,
            detail=f"找不到產線 {request.line_id}，可用：{sorted(valid_lines)}"
        )

    try:
        situation = build_situation(request.line_id)
        result = analyze_validated(situation)
        return result

    # 失敗類型二:LLM 連續失敗(analyze_validated 會 raise RuntimeError)
    #   → 這不是「使用者的錯」,也不是「永久壞掉」,是「暫時無法完成」
    #   → 用 503,並告訴呼叫方「可稍後重試」
    except RuntimeError as e:
        # 把詳細錯誤記在「伺服器端日誌」(給你/維運看),不是回給使用者
        logger.error(f"LLM 分析失敗 line={request.line_id}: {e}")
        raise HTTPException(
            status_code=503,
            detail="分析服務暫時無法完成請求，請稍後重試。"
        )
        
    # 新增:連不上 LLM 服務(Ollama 沒開、網路問題等)
    #   語意是「服務暫時不可用」→ 503,引導呼叫方稍後重試
    except openai.APIConnectionError as e:
        logger.error(f"無法連線 LLM 服務 line={request.line_id}: {e}")
        raise HTTPException(
            status_code=503,
            detail="無法連線分析服務，請確認服務狀態後稍後重試。"
        )

    # 失敗類型三:任何沒預期到的錯(DB 掛了、磁碟滿了…)
    #   → 回乾淨的 500,絕不把 traceback 洩漏給使用者
    except Exception as e:
        logger.error(f"未預期錯誤 line={request.line_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="伺服器內部發生未預期的錯誤。"
        )
        
# 檔案大小上限:10 MB(避免使用者上傳 GB 級檔案撐爆記憶體)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
RAG_RELEVANCE_THRESHOLD = 0.4   # 自適應 RAG 的相似度門檻


@app.post("/upload-and-analyze", response_model=DataInsight)
async def upload_and_analyze(file: UploadFile = File(...)):
    """接收 CSV 檔案,做 pandas 探勘 + 自適應 RAG + LLM 分析。
    沿用整個專案的核心架構:確定性歸程式、機率性歸 LLM、邊界用 Pydantic 守。
    """
    # ===== 第一層防禦:檔案類型檢查 =====
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail=f"只接受 CSV 檔案,你上傳的是:{file.filename}"
        )

    # ===== 第二層防禦:檔案大小限制 =====
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,    # 413 = Payload Too Large,語意精準
            detail=f"檔案超過 {MAX_UPLOAD_SIZE // (1024*1024)} MB 限制"
        )

    # ===== 第三層防禦:CSV 解析錯誤要乾淨報錯 =====
    try:
        df = load_csv_from_bytes(content)
    except Exception as e:
        logger.error(f"CSV 解析失敗 file={file.filename}: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"無法解析 CSV(請確認檔案格式):{type(e).__name__}"
        )

    # ===== 探勘 + 組情境(確定性,完全不碰 LLM) =====
    try:
        profile = explore_dataframe(df)
        situation = build_data_situation(profile)
    except Exception as e:
        logger.error(f"資料探勘失敗 file={file.filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="資料探勘階段發生錯誤")

    # ===== 自適應 RAG:相似度夠才用 =====
    try:
        query = " ".join(c["name"] for c in profile["columns"])
        hits = retrieve(query, top_k=2)
        relevant_hits = [h for h in hits if h["score"] >= RAG_RELEVANCE_THRESHOLD]
        kb_text = "\n\n".join(
            f"【{h['title']}】\n{h['content'].strip()}" for h in relevant_hits
        ) if relevant_hits else ""
        logger.info(
            f"RAG: 檢索 {len(hits)} 段,通過門檻 {len(relevant_hits)} 段"
        )
    except Exception as e:
        # RAG 失敗不該讓整個分析失敗——降級成「無 RAG」繼續
        logger.warning(f"RAG 檢索失敗,降級為無 RAG 繼續:{e}")
        kb_text = ""

    # ===== LLM 分析 =====
    try:
        result = analyze_dataset(situation, kb_context=kb_text)
        return result
    except RuntimeError as e:
        logger.error(f"LLM 分析失敗 file={file.filename}: {e}")
        raise HTTPException(
            status_code=503,
            detail="分析服務暫時無法完成請求,請稍後重試"
        )
    except openai.APIConnectionError as e:
        logger.error(f"無法連線 LLM 服務:{e}")
        raise HTTPException(
            status_code=503,
            detail="無法連線分析服務,請確認服務狀態"
        )
    except Exception as e:
        logger.error(f"未預期錯誤:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail="伺服器內部發生未預期的錯誤")
    
# 啟動壓縮的門檻:訊息數超過這個就觸發摘要
COMPRESSION_THRESHOLD = 10
# 壓縮後保留最近幾輪原文(其他壓成摘要)
KEEP_RECENT_MESSAGES = 4


def compress_history(messages: List[ChatMessage], model: str) -> List[ChatMessage]:
    """把過長的對話歷史壓縮:舊歷史用 LLM 摘要成一筆 system,保留最近 N 輪原文。
    這完整實作了階段 1 思考題推出的『摘要壓縮』策略。
    """
    # 分出「要壓縮的舊歷史」和「保留的最近 N 輪」
    to_compress = messages[:-KEEP_RECENT_MESSAGES]
    to_keep = messages[-KEEP_RECENT_MESSAGES:]

    # 把要壓縮的對話轉成可讀文字餵給 LLM
    history_text = "\n".join(
        f"{m.role}: {m.content}" for m in to_compress
    )

    summary_prompt = (
        "請把以下對話精簡摘要成一段繁體中文,"
        "保留關鍵事實、資料數字、已得出的結論,"
        "省略寒暄與重複內容。摘要本身不要超過 300 字。\n\n"
        f"對話內容:\n{history_text}"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": summary_prompt}],
    )
    summary = to_traditional(response.choices[0].message.content)

    # 用一筆 system 訊息代表「之前對話的摘要」
    summary_msg = ChatMessage(
        role="system",
        content=f"【過往對話摘要】{summary}"
    )

    return [summary_msg] + to_keep


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """多輪對話端點。API 無狀態:每次帶完整 messages 來、處理完不記任何東西。"""

    # ===== 把 Pydantic 物件轉成 dict,方便丟給 LLM =====
    messages_dict = [m.model_dump() for m in request.messages]
    was_compressed = False

    # ===== Step A:歷史壓縮(若啟用且超過門檻) =====
    if request.auto_compress and len(request.messages) > COMPRESSION_THRESHOLD:
        try:
            compressed = compress_history(request.messages, DEFAULT_MODEL)
            messages_dict = [m.model_dump() for m in compressed]
            was_compressed = True
            logger.info(
                f"歷史壓縮觸發:{len(request.messages)} 筆 → {len(compressed)} 筆"
            )
        except Exception as e:
            # 壓縮失敗不該讓整個對話掛掉,降級為「不壓縮繼續」
            logger.warning(f"歷史壓縮失敗,降級為不壓縮繼續:{e}")

    # ===== Step B:資料 profile(若有提供且還沒在歷史中) =====
    # 檢查歷史第一筆是不是已經是「帶資料的 system」,避免重複塞
    has_data_system = (
        len(messages_dict) > 0
        and messages_dict[0]["role"] == "system"
        and "資料概貌" in messages_dict[0].get("content", "")
    )
    if request.data_profile_text and not has_data_system:
        data_system = {
            "role": "system",
            "content": (
                "你是一位資料分析師,正在協助使用者理解他剛上傳的資料。"
                "全程使用繁體中文。回答要根據使用者實際提供的『資料概貌』,"
                "不要假設或杜撰任何不在資料裡的數字。\n\n"
                f"【資料概貌】\n{request.data_profile_text}"
            ),
        }
        messages_dict = [data_system] + messages_dict

    # ===== Step C:自適應 RAG(用最新使用者問題當查詢) =====
    latest_user_msg = next(
        (m for m in reversed(messages_dict) if m["role"] == "user"),
        None,
    )
    if latest_user_msg:
        try:
            hits = retrieve(latest_user_msg["content"], top_k=2)
            relevant = [h for h in hits if h["score"] >= RAG_RELEVANCE_THRESHOLD]
            if relevant:
                kb_text = "\n\n".join(
                    f"【{h['title']}】\n{h['content'].strip()}" for h in relevant
                )
                # 把 RAG 結果以 system 訊息插入,放在最後一筆 user 之前
                rag_system = {
                    "role": "system",
                    "content": (
                        "以下是與使用者最新問題相關的領域知識,參考時用:\n"
                        f"{kb_text}"
                    ),
                }
                # 找到最後一筆 user 的位置,把 RAG 插在它之前
                last_user_idx = max(
                    i for i, m in enumerate(messages_dict) if m["role"] == "user"
                )
                messages_dict.insert(last_user_idx, rag_system)
                logger.info(f"RAG 啟用:{len(relevant)} 段相關知識")
            else:
                logger.info("RAG 略過:無相關知識超過門檻")
        except Exception as e:
            logger.warning(f"RAG 失敗,降級為無 RAG 繼續:{e}")

    # ===== Step D:呼叫 LLM =====
    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages_dict,
        )
        reply = to_traditional(response.choices[0].message.content)
    except openai.APIConnectionError as e:
        logger.error(f"無法連線 LLM 服務:{e}")
        raise HTTPException(
            status_code=503,
            detail="無法連線分析服務,請確認服務狀態",
        )
    except Exception as e:
        logger.error(f"LLM 呼叫失敗:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail="伺服器內部錯誤")

    # ===== Step E:組裝回傳的「更新後完整訊息」 =====
    # 注意:回傳給前端的是「原本歷史 + 這輪的 assistant 回應」
    # 而不是 messages_dict(那個包含暫時插入的 RAG/壓縮,前端不該看到)
    updated = list(request.messages) + [
        ChatMessage(role="assistant", content=reply)
    ]
    return ChatResponse(
        updated_messages=updated,
        was_compressed=was_compressed,
    )