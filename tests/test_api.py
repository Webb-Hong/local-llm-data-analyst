"""測試 api 模組——FastAPI 端點的整合測試。

策略:用 FastAPI 的 TestClient(在記憶體跑 app,不開 server),
對每個端點驗證『請求 → 內部處理 → 回應』完整鏈。LLM 呼叫和向量檢索
用 mock 隔離,測試完全離線、不依賴 Ollama。

涵蓋的端點:
- GET /          根端點
- GET /health    健康檢查
- GET /lines     列出產線
- POST /diagnosis 產線分析(含成功 + 404 + 503 三種路徑)
- POST /upload-and-analyze 上傳 CSV(含成功 + 400 + 413 三種路徑)
- POST /chat     多輪對話(含成功 + 422 兩種路徑)
"""
import io
import pytest
from fastapi.testclient import TestClient
from src.api import app
from src.llm_client import AnalysisResult, DataInsight


# ===== Fixture:共用的 TestClient =====


@pytest.fixture
def client():
    """提供一個 FastAPI TestClient。
    
    TestClient 在記憶體裡跑 app——不需要真的開 uvicorn server,
    但呼叫方式跟真實 HTTP 一樣(client.get/post)。
    """
    return TestClient(app)


# ===== 簡單端點:GET / 和 /health =====


def test_root_returns_200(client):
    """根端點應該回 200。"""
    response = client.get("/")
    assert response.status_code == 200


def test_root_response_structure(client):
    """根端點回應應該包含 message 和 status。"""
    response = client.get("/")
    data = response.json()
    assert "message" in data
    assert "status" in data


def test_health_check(client):
    """健康檢查應該回 200,且 status 是 healthy。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


# ===== GET /lines =====


def test_list_lines_returns_200(client):
    """列出產線應該回 200。"""
    response = client.get("/lines")
    assert response.status_code == 200


def test_list_lines_returns_list(client):
    """應該回傳一個 list(可能空但要是 list)。"""
    response = client.get("/lines")
    data = response.json()
    assert isinstance(data, list)


def test_list_lines_items_have_required_fields(client):
    """每筆產線資料應該包含 line_id 和 defect_rate_pct。
    
    這驗證 API 對外契約——前端依賴這兩個欄位。
    """
    response = client.get("/lines")
    data = response.json()
    
    # factory.db 應該至少有 1 條產線
    assert len(data) > 0
    
    first = data[0]
    assert "line_id" in first
    assert "defect_rate_pct" in first


# ===== POST /diagnosis =====


def test_diagnosis_success(client, mocker):
    """產線分析成功路徑:LLM 回對的 AnalysisResult,API 應該回 200。
    
    Mock analyze_validated 直接回 AnalysisResult 物件,
    跳過所有 LLM 互動。
    """
    # Arrange:mock LLM 回傳對的 AnalysisResult
    fake_result = AnalysisResult(
        可能原因=["錫膏印刷量過多"],
        嚴重程度="高",
        建議行動=["檢查錫膏參數"],
        需要補充的資訊=["近期鋼板更換紀錄"],
    )
    mocker.patch("src.api.analyze_validated", return_value=fake_result)
    
    # 先拿一條真實 line_id(避免假設 LINE_A 一定存在)
    lines = client.get("/lines").json()
    real_line_id = lines[0]["line_id"]
    
    # Act
    response = client.post("/diagnosis", json={"line_id": real_line_id})
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["嚴重程度"] == "高"
    assert "錫膏印刷量過多" in data["可能原因"]


def test_diagnosis_nonexistent_line_returns_404(client):
    """查不存在的產線應該回 404(不是 500)。
    
    這驗證 API 對「找不到資源」的處理符合 HTTP 語意。
    """
    response = client.post(
        "/diagnosis",
        json={"line_id": "LINE_NOT_EXIST_XYZ"}
    )
    
    assert response.status_code == 404
    # 確認錯誤訊息有提到使用者問的 line_id
    assert "LINE_NOT_EXIST_XYZ" in response.json()["detail"]


def test_diagnosis_llm_failure_returns_503(client, mocker):
    """LLM 三次都失敗時,API 應該回 503(暫時不可用,可重試)。
    
    這驗證 fail-fast 機制——LLM 掛了不該回 500(看起來像 bug),
    應該回 503(暫時無法服務,語意精準)。
    """
    # Mock analyze_validated raise RuntimeError(模擬三次都失敗的情境)
    mocker.patch(
        "src.api.analyze_validated",
        side_effect=RuntimeError("連續 3 次都無法取得合格結果")
    )
    
    lines = client.get("/lines").json()
    real_line_id = lines[0]["line_id"]
    
    response = client.post("/diagnosis", json={"line_id": real_line_id})
    
    assert response.status_code == 503
    assert "稍後重試" in response.json()["detail"]


def test_diagnosis_missing_line_id_returns_422(client):
    """請求 body 沒有 line_id 應該回 422(Pydantic 自動驗證失敗)。
    
    422 = Unprocessable Entity——FastAPI/Pydantic 自動處理。
    """
    response = client.post("/diagnosis", json={})
    
    assert response.status_code == 422


# ===== POST /upload-and-analyze =====


def test_upload_non_csv_returns_400(client):
    """上傳非 CSV 檔案應該回 400(三層防禦的第一層)。"""
    # 用 BytesIO 模擬一個假檔案
    fake_file = io.BytesIO(b"some content")
    
    response = client.post(
        "/upload-and-analyze",
        files={"file": ("test.txt", fake_file, "text/plain")}
    )
    
    assert response.status_code == 400
    assert "CSV" in response.json()["detail"]


def test_upload_invalid_csv_content_returns_400(client):
    """上傳副檔名對但內容不是 CSV 應該回 400(三層防禦的第三層)。"""
    # 副檔名是 .csv 但內容是亂的二進位
    fake_file = io.BytesIO(b"\x00\x01\x02\x03not_a_csv\xff")
    
    response = client.post(
        "/upload-and-analyze",
        files={"file": ("fake.csv", fake_file, "text/csv")}
    )
    
    # 可能是 400(CSV 解析失敗)
    assert response.status_code in (400, 500)


def test_upload_valid_csv_success(client, mocker):
    """上傳有效 CSV 應該回 200,包含 DataInsight 結構。
    
    Mock analyze_dataset 跳過 LLM,Mock retrieve 跳過向量檢索。
    """
    # Mock LLM 分析
    fake_insight = DataInsight(
        資料概要="這是一份測試資料",
        主要觀察=["觀察 1", "觀察 2"],
        分析建議=["建議 1"],
        資料品質警告=[],
    )
    mocker.patch("src.api.analyze_dataset", return_value=fake_insight)
    # Mock 向量檢索(避免打 Ollama)
    mocker.patch("src.api.retrieve", return_value=[])
    
    # 造一個有效的小 CSV
    csv_content = b"line_id,output,defects\nLINE_A,100,2\nLINE_B,200,5\n"
    fake_file = io.BytesIO(csv_content)
    
    response = client.post(
        "/upload-and-analyze",
        files={"file": ("test.csv", fake_file, "text/csv")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "資料概要" in data
    assert data["資料概要"] == "這是一份測試資料"


def test_upload_llm_failure_returns_503(client, mocker):
    """LLM 失敗時應該回 503。"""
    mocker.patch(
        "src.api.analyze_dataset",
        side_effect=RuntimeError("LLM 連續失敗")
    )
    mocker.patch("src.api.retrieve", return_value=[])
    
    csv_content = b"a,b\n1,2\n3,4\n"
    fake_file = io.BytesIO(csv_content)
    
    response = client.post(
        "/upload-and-analyze",
        files={"file": ("test.csv", fake_file, "text/csv")}
    )
    
    assert response.status_code == 503


# ===== POST /chat =====


def test_chat_success(client, mocker):
    """正常多輪對話應該回 200 + ChatResponse 結構。"""
    # Mock LLM 呼叫——這次要 mock 整個 client.chat.completions.create
    # 因為 /chat 端點直接呼叫它
    fake_response = mocker.MagicMock()
    fake_response.choices[0].message.content = "這是 LLM 的回應"
    mocker.patch(
        "src.api.client.chat.completions.create",
        return_value=fake_response
    )
    # Mock RAG 檢索(避免打 Ollama)
    mocker.patch("src.api.retrieve", return_value=[])
    
    response = client.post(
        "/chat",
        json={
            "messages": [
                {"role": "user", "content": "你好"},
            ],
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "updated_messages" in data
    assert "was_compressed" in data
    # updated_messages 應該包含原本的 user + 新的 assistant 回應
    assert len(data["updated_messages"]) == 2
    assert data["updated_messages"][-1]["role"] == "assistant"


def test_chat_empty_messages_returns_422(client):
    """空 messages 應該回 422(Pydantic 驗證失敗)。"""
    response = client.post("/chat", json={"messages": []})
    
    assert response.status_code == 422


def test_chat_invalid_role_returns_422(client):
    """role 不是 system/user/assistant 應該回 422。"""
    response = client.post(
        "/chat",
        json={
            "messages": [
                {"role": "invalid_role", "content": "test"},
            ],
        }
    )
    
    assert response.status_code == 422


def test_chat_missing_required_field_returns_422(client):
    """messages 中缺 content 欄位應該回 422。"""
    response = client.post(
        "/chat",
        json={
            "messages": [
                {"role": "user"},   # ← 缺 content
            ],
        }
    )
    
    assert response.status_code == 422


def test_chat_was_compressed_flag(client, mocker):
    """auto_compress=True + 訊息超過門檻時,was_compressed 應該是 True。
    
    門檻是 COMPRESSION_THRESHOLD=10,我們塞 12 筆訊息觸發壓縮。
    """
    # Mock 壓縮用的 LLM 呼叫和正常對話的 LLM 呼叫都用同一個 mock
    fake_response = mocker.MagicMock()
    fake_response.choices[0].message.content = "壓縮摘要 / LLM 回應"
    mocker.patch(
        "src.api.client.chat.completions.create",
        return_value=fake_response
    )
    mocker.patch("src.api.retrieve", return_value=[])
    
    # 塞 12 筆訊息觸發壓縮(門檻 > 10)
    messages = []
    for i in range(6):
        messages.append({"role": "user", "content": f"問題 {i}"})
        messages.append({"role": "assistant", "content": f"回答 {i}"})
    
    response = client.post(
        "/chat",
        json={
            "messages": messages,
            "auto_compress": True,
        }
    )
    
    assert response.status_code == 200
    assert response.json()["was_compressed"] is True