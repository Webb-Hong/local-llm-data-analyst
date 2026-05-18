"""製造資料分析模組。
職責：用 SQL 從資料庫算出『確定性的數據事實』，
例如各產線不良率、是否有時間區段異常升高。
這一層完全不碰 LLM —— 數字必須精確，不容機率性誤差。
"""
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "factory.db")


def get_line_defect_rates(db_path: str = DB_PATH) -> list[dict]:
    """算出每條產線的整體不良率。
    回傳像 [{'line_id': 'LINE_A', 'defect_rate_pct': 2.01}, ...]
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT line_id,
               SUM(output)  AS total_output,
               SUM(defects) AS total_defects,
               ROUND(100.0 * SUM(defects) / SUM(output), 2) AS defect_rate_pct
        FROM production
        GROUP BY line_id
        ORDER BY defect_rate_pct DESC
    """)
    cols = [d[0] for d in cur.description]   # 取欄位名
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def get_monthly_trend(line_id: str, db_path: str = DB_PATH) -> list[dict]:
    """算出指定產線『逐月』不良率趨勢，用來看是不是某段時間突然惡化。
    用 SQL 的字串函式把日期切出『年-月』來分組。
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT substr(prod_date, 1, 7) AS month,
               ROUND(100.0 * SUM(defects) / SUM(output), 2) AS defect_rate_pct
        FROM production
        WHERE line_id = ?
        GROUP BY month
        ORDER BY month
    """, (line_id,))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def build_situation(line_id: str, db_path: str = DB_PATH) -> str:
    """把 SQL 算出的『確定數據事實』組裝成一段給 LLM 看的情境敘述。
    注意：這裡的數字全部來自 SQL 精確計算，LLM 只會『解讀』這些數字，
    不會也不該自己算任何數字。
    """
    trend = get_monthly_trend(line_id, db_path)
    all_rates = get_line_defect_rates(db_path)

    # 找出這條線的整體不良率(從已算好的結果裡撈，不重算)
    this_line = next(r for r in all_rates if r["line_id"] == line_id)

    # 把逐月趨勢攤成可讀文字
    trend_text = "、".join(
        f'{r["month"]} 為 {r["defect_rate_pct"]}%' for r in trend
    )

    situation = (
        f"產線 {line_id} 的品質數據如下（數字均為系統精確統計，非估計）：\n"
        f"- 整體不良率：{this_line['defect_rate_pct']}%\n"
        f"- 逐月不良率趨勢：{trend_text}\n"
        f"請根據以上『已確定的數據』進行分析，"
        f"不要自行假設或更動任何數字。"
    )
    return situation


if __name__ == "__main__":
    print("===== 各產線整體不良率 =====")
    for r in get_line_defect_rates():
        print(r)
    print("\n===== build_situation(LINE_B) 產出的情境 =====")
    print(build_situation("LINE_B"))