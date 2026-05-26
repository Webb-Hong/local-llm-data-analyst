"""測試 analyzer 模組的 SQL 邏輯。

核心挑戰:這些函式依賴 SQLite 資料庫,測試要怎麼處理?
解法:用 pytest fixture 建立『測試專用的臨時資料庫』,
測試前自動建好假資料、測試後自動清掉,讓每個測試都在乾淨環境跑。
"""
import sqlite3
import pytest
from src.analyzer import get_line_defect_rates, get_monthly_trend


# ===== Fixture:建立測試用資料庫 =====


@pytest.fixture
def test_db(tmp_path):
    """建立一個臨時測試資料庫,測試結束後自動清掉。
    
    使用 pytest 內建的 tmp_path fixture——它會給每個測試一個獨立的
    臨時資料夾(在 OS 的 temp 區),測試跑完 pytest 自動清。
    
    這個設計讓:
    - 測試彼此獨立(各自有自己的 db)
    - 不污染 production 的 factory.db
    - 每次測試環境都是乾淨的
    """
    # tmp_path 是 pathlib.Path 物件,指向一個臨時資料夾
    db_path = str(tmp_path / "test_factory.db")
    
    # 連線並建立表(模仿 make_data.py 的 schema)
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
    
    # 插入測試用假資料(刻意設計,讓不良率好驗算)
    # LINE_A: 1000+1000 output, 10+20 defects → 30/2000 = 1.5%
    # LINE_B: 1000+1000 output, 30+50 defects → 80/2000 = 4.0%  ← 最高
    # LINE_C: 1000 output, 20 defects → 20/1000 = 2.0%
    test_data = [
        ("LINE_A", "2025-01-01", 1000, 10),
        ("LINE_A", "2025-02-01", 1000, 20),
        ("LINE_B", "2025-01-01", 1000, 30),
        ("LINE_B", "2025-02-01", 1000, 50),
        ("LINE_C", "2025-01-01", 1000, 20),
    ]
    cur.executemany(
        "INSERT INTO production VALUES (?, ?, ?, ?)",
        test_data
    )
    conn.commit()
    conn.close()
    
    # yield 把 db_path 交給測試使用
    yield db_path
    
    # yield 之後的 code 會在測試結束後跑——
    # 但因為 tmp_path 是自動清的,我們不用手動清,
    # 這裡留空當示範


# ===== 測試 get_line_defect_rates =====


def test_get_line_defect_rates_returns_correct_count(test_db):
    """應該回傳 3 條產線(LINE_A, B, C)。"""
    result = get_line_defect_rates(db_path=test_db)
    
    assert len(result) == 3


def test_get_line_defect_rates_structure(test_db):
    """每筆結果應該有 4 個欄位:line_id, total_output, total_defects, defect_rate_pct。"""
    result = get_line_defect_rates(db_path=test_db)
    
    # 拿第一筆看結構
    first = result[0]
    assert "line_id" in first
    assert "total_output" in first
    assert "total_defects" in first
    assert "defect_rate_pct" in first


def test_get_line_defect_rates_values(test_db):
    """驗證 SQL 算的不良率正確。
    
    根據 fixture 裡塞的假資料:
    - LINE_A: 30 defects / 2000 output = 1.5%
    - LINE_B: 80 defects / 2000 output = 4.0%
    - LINE_C: 20 defects / 1000 output = 2.0%
    """
    result = get_line_defect_rates(db_path=test_db)
    
    # 轉成 dict 方便查(用 line_id 當 key)
    rates_by_line = {r["line_id"]: r["defect_rate_pct"] for r in result}
    
    assert rates_by_line["LINE_A"] == pytest.approx(1.5)
    assert rates_by_line["LINE_B"] == pytest.approx(4.0)
    assert rates_by_line["LINE_C"] == pytest.approx(2.0)


def test_get_line_defect_rates_sorted_by_rate_desc(test_db):
    """結果應該按不良率降冪排序(最差的線最前面)。
    
    這個排序是 SQL 的 ORDER BY defect_rate_pct DESC 決定的——
    測試這個排序契約,讓未來有人改 SQL 排序時會被擋下。
    """
    result = get_line_defect_rates(db_path=test_db)
    
    # 第一筆應該是最差的 LINE_B(4.0%)
    assert result[0]["line_id"] == "LINE_B"
    # 最後一筆應該是最好的 LINE_A(1.5%)
    assert result[-1]["line_id"] == "LINE_A"


# ===== 測試 get_monthly_trend =====


def test_get_monthly_trend_returns_data_for_existing_line(test_db):
    """對存在的產線,應該回傳每月不良率。"""
    result = get_monthly_trend("LINE_A", db_path=test_db)
    
    # LINE_A 有兩個月的資料(2025-01, 2025-02)
    assert len(result) == 2


def test_get_monthly_trend_structure(test_db):
    """每筆應該有 month 和 defect_rate_pct 兩個欄位。"""
    result = get_monthly_trend("LINE_A", db_path=test_db)
    
    first = result[0]
    assert "month" in first
    assert "defect_rate_pct" in first


def test_get_monthly_trend_values(test_db):
    """驗證月趨勢計算正確。
    
    LINE_A:
    - 2025-01: 10/1000 = 1.0%
    - 2025-02: 20/1000 = 2.0%
    """
    result = get_monthly_trend("LINE_A", db_path=test_db)
    
    # 轉成 dict 方便查
    by_month = {r["month"]: r["defect_rate_pct"] for r in result}
    
    assert by_month["2025-01"] == pytest.approx(1.0)
    assert by_month["2025-02"] == pytest.approx(2.0)


def test_get_monthly_trend_sorted_by_month(test_db):
    """結果應該按月份升冪排序(舊的在前)。"""
    result = get_monthly_trend("LINE_A", db_path=test_db)
    
    assert result[0]["month"] == "2025-01"
    assert result[1]["month"] == "2025-02"


def test_get_monthly_trend_nonexistent_line_returns_empty(test_db):
    """查不存在的產線,應該回傳空 list(SQL 行為,不該炸)。
    
    這個邊界測試很重要——SQL 對『沒符合 WHERE 的查詢』
    自然回空 list,但我們要『明確驗證這個行為』,
    避免未來有人改 SQL 不小心讓它 raise。
    """
    result = get_monthly_trend("LINE_NOT_EXIST", db_path=test_db)
    
    assert result == []