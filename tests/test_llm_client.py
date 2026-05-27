"""測試 llm_client 模組——LLM 互動邏輯。

核心挑戰:這些函式呼叫真實 LLM(Ollama),測試不能真的打 LLM
(慢、不穩、耗 token)。解法:用 mock 取代 client.chat.completions.create,
讓測試完全在記憶體跑,精準控制「LLM 假裝回了什麼」。

測試重點放在 analyze_validated:
- 重試邏輯(失敗 N 次才成功 / 三次都失敗)
- Pydantic 驗證(JSON 格式錯、業務規則錯)
- fail-fast 行為(超過重試上限 raise)

不測「LLM 真的回了對的東西」——那是 LLM 的事,我們的程式只負責
『拿到的不對就重試、最終不對就明確失敗』。
"""
import json
import pytest
from unittest.mock import MagicMock
from pydantic import ValidationError
from src.llm_client import analyze_validated, AnalysisResult


# ===== Helper:建立假的 LLM 回應 =====


def make_fake_llm_response(content: str):
    """造一個假的 LLM 回應物件,模擬 OpenAI SDK 回傳的結構。
    
    OpenAI SDK 的回應結構是 response.choices[0].message.content
    我們用 MagicMock 模擬這個三層巢狀結構。
    
    這個 helper 讓每個測試只要關心『LLM 假裝回了什麼字串』,
    不用每次重寫整個 mock 結構。
    """
    fake_response = MagicMock()
    fake_response.choices[0].message.content = content
    return fake_response


# ===== Helper:有效的 LLM 回應字串 =====


VALID_LLM_OUTPUT = json.dumps({
    "可能原因": ["錫膏印刷量過多", "鋼板開孔過大"],
    "嚴重程度": "高",
    "建議行動": ["檢查錫膏參數", "檢查鋼板"],
    "需要補充的資訊": ["近期鋼板更換紀錄"],
}, ensure_ascii=False)


# ===== 測試 1:第一次就成功 =====


def test_analyze_validated_success_on_first_try(mocker):
    """LLM 第一次就回對的 JSON,函式應該直接回傳 AnalysisResult。
    
    這是 happy path——驗證『正常情況的最短路徑』。
    """
    # Arrange:設定 mock,讓 LLM 假裝回對的 JSON
    mock_create = mocker.patch("src.llm_client.client.chat.completions.create")
    mock_create.return_value = make_fake_llm_response(VALID_LLM_OUTPUT)
    
    # Act
    result = analyze_validated("測試情境")
    
    # Assert:
    # 1. 回傳的是 AnalysisResult 物件
    assert isinstance(result, AnalysisResult)
    # 2. 內容符合 mock 回應
    assert result.嚴重程度 == "高"
    assert "錫膏印刷量過多" in result.可能原因
    # 3. LLM 只被呼叫一次(沒重試)
    assert mock_create.call_count == 1


# ===== 測試 2:JSON 壞、重試後成功 =====


def test_analyze_validated_retries_on_bad_json(mocker):
    """LLM 第一次回壞 JSON,第二次回對的——函式應該重試並成功。
    
    這驗證『JSON 解析失敗時的重試機制』——對應 except json.JSONDecodeError。
    """
    # Arrange:用 side_effect 讓 mock 兩次回不同結果
    # side_effect 是 list 時,每次呼叫依序回傳列表元素
    mock_create = mocker.patch("src.llm_client.client.chat.completions.create")
    mock_create.side_effect = [
        make_fake_llm_response("這不是 JSON,只是普通文字"),   # 第一次:壞 JSON
        make_fake_llm_response(VALID_LLM_OUTPUT),              # 第二次:對的
    ]
    
    # Act
    result = analyze_validated("測試情境")
    
    # Assert:
    # 1. 終究成功
    assert isinstance(result, AnalysisResult)
    # 2. LLM 被呼叫了兩次(第一次失敗、重試一次成功)
    assert mock_create.call_count == 2


# ===== 測試 3:Pydantic 驗證失敗、重試成功 =====


def test_analyze_validated_retries_on_pydantic_failure(mocker):
    """LLM 第一次回的 JSON 格式對但業務規則錯(嚴重程度非法),
    第二次回對的——函式應該重試並成功。
    
    這驗證『JSON 過但 Pydantic 業務驗證失敗』時的重試——對應 except ValueError。
    Pydantic 驗證失敗會 raise ValidationError,而 ValidationError 繼承自 ValueError。
    """
    bad_output = json.dumps({
        "可能原因": ["錫膏印刷量過多"],
        "嚴重程度": "極高",   # ← 非法值!Pydantic validator 會擋下(只能 高/中/低)
        "建議行動": ["檢查錫膏參數"],
        "需要補充的資訊": [],
    }, ensure_ascii=False)
    
    mock_create = mocker.patch("src.llm_client.client.chat.completions.create")
    mock_create.side_effect = [
        make_fake_llm_response(bad_output),       # 第一次:Pydantic fail
        make_fake_llm_response(VALID_LLM_OUTPUT), # 第二次:對的
    ]
    
    result = analyze_validated("測試情境")
    
    assert isinstance(result, AnalysisResult)
    assert mock_create.call_count == 2


# ===== 測試 4:三次都失敗,應該 raise RuntimeError =====


def test_analyze_validated_raises_after_max_retries(mocker):
    """LLM 三次都回壞東西,函式應該 raise RuntimeError(fail-fast)。
    
    這是最重要的測試——驗證『系統會明確失敗,不會默默回不對的資料』。
    對應你架構的核心原則:Pydantic 是確定性關卡,過不了就 fail-fast。
    """
    mock_create = mocker.patch("src.llm_client.client.chat.completions.create")
    # 三次都回壞 JSON
    mock_create.return_value = make_fake_llm_response("亂回的不是 JSON")
    
    # Act & Assert:應該 raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        analyze_validated("測試情境")
    
    # 確認錯誤訊息包含關鍵字「連續 3 次」
    assert "3 次" in str(exc_info.value) or "連續" in str(exc_info.value)
    # 確認真的試了 3 次
    assert mock_create.call_count == 3


# ===== 測試 5:max_retries=1,失敗就立刻 raise =====


def test_analyze_validated_respects_max_retries_parameter(mocker):
    """max_retries 參數應該真的控制重試次數。
    
    設 max_retries=1,失敗一次就該立刻 raise,不會再試。
    """
    mock_create = mocker.patch("src.llm_client.client.chat.completions.create")
    mock_create.return_value = make_fake_llm_response("壞 JSON")
    
    with pytest.raises(RuntimeError):
        analyze_validated("測試情境", max_retries=1)
    
    # 確認只試了 1 次(不是預設的 3 次)
    assert mock_create.call_count == 1


# ===== 測試 6:Pydantic 業務規則(嚴重程度非法值)真的會擋 =====


def test_pydantic_rejects_invalid_severity():
    """直接測 Pydantic model:嚴重程度只能是 高/中/低,其他值應該 raise。
    
    這是『不依賴 LLM 的純 Pydantic 測試』——驗證我們的驗證邏輯本身正確。
    """
    with pytest.raises(ValidationError):
        AnalysisResult(
            可能原因=["原因1"],
            嚴重程度="極高",   # 非法值
            建議行動=["行動1"],
            需要補充的資訊=[],
        )


def test_pydantic_rejects_empty_possible_causes():
    """『可能原因』不能是空陣列,空陣列應該被擋下。"""
    with pytest.raises(ValidationError):
        AnalysisResult(
            可能原因=[],   # 空陣列!
            嚴重程度="高",
            建議行動=["行動1"],
            需要補充的資訊=[],
        )


def test_pydantic_rejects_empty_actions():
    """『建議行動』也不能是空陣列。"""
    with pytest.raises(ValidationError):
        AnalysisResult(
            可能原因=["原因1"],
            嚴重程度="高",
            建議行動=[],   # 空陣列!
            需要補充的資訊=[],
        )


# ===== 測試 7:嚴重程度三個合法值都該過 =====


@pytest.mark.parametrize("severity", ["高", "中", "低"])
def test_pydantic_accepts_all_valid_severities(severity):
    """『高、中、低』三個值都應該通過驗證。
    
    用 parametrize 一支測三個案例。
    """
    result = AnalysisResult(
        可能原因=["原因1"],
        嚴重程度=severity,
        建議行動=["行動1"],
        需要補充的資訊=[],
    )
    
    assert result.嚴重程度 == severity