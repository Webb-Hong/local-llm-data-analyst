"""FastAPI 服務：把製造分析引擎包成 RESTful API。"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from analyzer import get_line_defect_rates, build_situation
from llm_client import analyze_validated, AnalysisResult

app = FastAPI(title="製造分析 API", version="0.2.0")


# ===== 輸入模型：定義「一個合法的分析請求」長什麼樣 =====
class DiagnosisRequest(BaseModel):
    line_id: str   # 使用者必須提供要分析哪條產線


@app.get("/")
def read_root():
    return {"message": "製造分析 API 運行中", "status": "ok"}


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
    # request.line_id 已被 DiagnosisRequest 驗證過(必須是字串、必須有值)
    valid_lines = {r["line_id"] for r in get_line_defect_rates()}

    # 防呆:使用者傳了不存在的產線,明確回 404,不要讓它往下爆
    if request.line_id not in valid_lines:
        raise HTTPException(
            status_code=404,
            detail=f"找不到產線 {request.line_id}，可用：{sorted(valid_lines)}"
        )

    # 執行你階段 2 已完成的整條鏈:SQL 事實 → LLM 解讀 → Pydantic 驗證
    situation = build_situation(request.line_id)
    result = analyze_validated(situation)   # 回傳的就是 AnalysisResult
    return result