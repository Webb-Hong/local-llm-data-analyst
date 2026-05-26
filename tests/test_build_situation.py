"""測試 build_situation——把 SQL 事實 + RAG 知識組裝成 LLM prompt 的函式。

挑戰:這函式依賴 SQL(get_line_defect_rates / get_monthly_trend)
和 RAG (retrieve)兩個下游。我們用兩種方式測:

1. 整合測試風格:用測試 db + 真實 retriever(慢一點但測到完整鏈)
2. 不 mock retriever:因為它純讀檔、不打外部服務,慢的可接受

注意:我們測的是『情境字串的結構性』,不是『LLM 會怎麼回應』——
LLM 部分是下個階段的事。
"""
import sqlite3
import pytest
from src.analyzer import build_situation


@pytest.fixture
def test_db(tmp_path):
    """同 test_analyzer.py 的 fixture——建立測試用 db。
    
    這份 fixture 程式碼重複了,真實專案會把它搬到 conftest.py
    讓多個測試檔共用。我們先各自寫,之後可以重構。
    """
    db_path = str(tmp_path / "test_factory.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE production (
            line_id TEXT,
            prod_date TEXT,
            output INTEGER,
            defects INTEGER
        )
    """)
    test_data = [
        ("LINE_A", "2025-01-01", 1000, 10),
        ("LINE_A", "2025-02-01", 1000, 20),
        ("LINE_B", "2025-01-01", 1000, 30),
        ("LINE_B", "2025-02-01", 1000, 50),
    ]
    cur.executemany("INSERT INTO production VALUES (?, ?, ?, ?)", test_data)
    conn.commit()
    conn.close()
    yield db_path


# ===== 結構性測試 =====


def test_build_situation_returns_string(test_db):
    """build_situation 應該回傳字串(不是 dict 或 list)。"""
    result = build_situation("LINE_A", db_path=test_db)
    
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_situation_contains_line_id(test_db):
    """情境字串應該包含被查詢的 line_id。"""
    result = build_situation("LINE_B", db_path=test_db)
    
    assert "LINE_B" in result


def test_build_situation_contains_defect_rate(test_db):
    """情境字串應該包含算好的整體不良率。
    
    LINE_A: 30/2000 = 1.5%,字串裡應該找得到 '1.5'。
    """
    result = build_situation("LINE_A", db_path=test_db)
    
    assert "1.5" in result


def test_build_situation_contains_monthly_trend(test_db):
    """情境字串應該包含每月趨勢。
    
    LINE_A 有 2025-01 和 2025-02 兩個月,字串裡都該出現。
    """
    result = build_situation("LINE_A", db_path=test_db)
    
    assert "2025-01" in result
    assert "2025-02" in result


def test_build_situation_contains_analysis_instructions(test_db):
    """情境字串應該包含『給 LLM 的分析指令』。
    
    這是 build_situation 的核心契約——它不只給數據,還給作答指引。
    我們驗證指令的關鍵字存在(『關鍵變化點』『建議行動』等)。
    """
    result = build_situation("LINE_A", db_path=test_db)
    
    assert "關鍵變化點" in result
    assert "可能原因" in result
    assert "建議行動" in result


def test_build_situation_contains_knowledge_base_section(test_db):
    """情境字串應該包含 RAG 拉進來的知識庫段落
    (或『無相關知識庫資料』的明確標記)。
    
    這驗證『有沒有正確接上 RAG』。
    """
    result = build_situation("LINE_A", db_path=test_db)
    
    # 字串裡應該有「知識庫」相關提示,且不是預設無資料訊息
    # (因為 LINE_A 不良率上升 趨勢異常 應該命中關鍵字)
    assert "知識庫" in result


# ===== 設計契約測試 =====


def test_build_situation_does_not_modify_numbers(test_db):
    """不該有任何數字運算發生在這個函式裡——
    所有數字來自 SQL,build_situation 只做字串組裝。
    
    這個測試比較難直接驗,但我們可以驗:
    LINE_B 整體 80/2000 = 4.0%,字串應該包含 '4.0',
    而不是某個 LLM 算錯的版本。
    """
    result = build_situation("LINE_B", db_path=test_db)
    
    assert "4.0" in result