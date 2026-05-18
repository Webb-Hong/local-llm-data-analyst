"""產生一份假的製造資料，存進 SQLite。
情境：3 條產線、90 天、每天的產量與不良數。
其中 LINE_B 在後 30 天被刻意埋入『不良率異常升高』，
這樣後面分析模組才有東西可以抓出來。
"""
import sqlite3
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)  # 固定亂數種子，讓每次產生的資料一樣(可重現，面試加分觀念)

# __file__ 是「這支程式檔自己的路徑」
# .resolve() 轉成絕對路徑；.parent.parent 往上兩層到專案根目錄
#   src/make_data.py → parent=src/ → parent.parent=專案根/
# 這樣不管從哪裡執行，DB_PATH 都穩定指向「專案根/factory.db」
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "factory.db")

def make_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 建立資料表：產線、日期、產量、不良數
    cur.execute("DROP TABLE IF EXISTS production")
    cur.execute("""
        CREATE TABLE production (
            line_id   TEXT,
            prod_date TEXT,
            output    INTEGER,
            defects   INTEGER
        )
    """)

    start = date(2025, 1, 1)
    rows = []
    for day_offset in range(90):
        d = start + timedelta(days=day_offset)
        for line in ["LINE_A", "LINE_B", "LINE_C"]:
            output = random.randint(900, 1100)
            # 基準不良率約 2%
            defect_rate = 0.02
            # 埋伏筆：LINE_B 在第 60 天後，不良率升到約 5%
            if line == "LINE_B" and day_offset >= 60:
                defect_rate = 0.05
            defects = int(output * defect_rate * random.uniform(0.8, 1.2))
            rows.append((line, d.isoformat(), output, defects))

    cur.executemany(
        "INSERT INTO production VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()

    # 驗證：印出每條線的平均不良率，確認資料有產出來
    cur.execute("""
        SELECT line_id,
               ROUND(100.0 * SUM(defects) / SUM(output), 2) AS defect_rate_pct
        FROM production
        GROUP BY line_id
    """)
    print("各產線整體不良率(%)：")
    for line_id, rate in cur.fetchall():
        print(f"  {line_id}: {rate}%")

    conn.close()
    print(f"\n資料已寫入 {DB_PATH}")

if __name__ == "__main__":
    make_data()