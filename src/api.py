"""FastAPI 服務：把製造分析引擎包成 RESTful API。"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai

from src.analyzer import get_line_defect_rates, build_situation
from src.llm_client import analyze_validated, AnalysisResult

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