"""FastAPI 服務：把製造分析引擎包成 RESTful API。"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai

from src.analyzer import get_line_defect_rates, build_situation
from src.llm_client import analyze_validated, AnalysisResult
from fastapi import UploadFile, File
from src.data_explorer import load_csv_from_bytes, explore_dataframe, build_data_situation
from src.llm_client import analyze_dataset, DataInsight
from src.vector_retriever import retrieve

import logging

# 設定一個 logger,用來把錯誤記錄到伺服器端(不是回給使用者)
logging.basicConfig(level=logging.INFO)        # 設門檻=INFO
logger = logging.getLogger(__name__)           # 建一個以模組名為名的 logger

app = FastAPI(title="製造分析 API", version="0.2.0")


# ===== 輸入模型：定義「一個合法的分析請求」長什麼樣 =====
class DiagnosisRequest(BaseModel):
    line_id: str   # 使用者必須提供要分析哪條產線


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