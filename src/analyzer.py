"""製造資料分析模組。
職責：用 SQL 從資料庫算出『確定性的數據事實』，
例如各產線不良率、是否有時間區段異常升高。
這一層完全不碰 LLM —— 數字必須精確，不容機率性誤差。
"""
import sqlite3
from pathlib import Path
from src.retriever import retrieve   # 檔案上方 import 區加這行

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
    
    # ===== RAG:用「這條線的狀況」當查詢,檢索相關製造知識 =====
    query = f"{line_id} 不良率上升 趨勢異常 排查"
    kb_hits = retrieve(query, top_k=2)
    if kb_hits:
        kb_text = "\n\n".join(
            f"【{s['title']}】\n{s['content'].strip()}" for s in kb_hits
        )
    else:
        kb_text = "(無相關知識庫資料)"

    situation = (
        f"以下是公司內部製造知識庫的相關資料：\n"
        f"========\n{kb_text}\n========\n\n"
        f"產線 {line_id} 的品質數據（數字均為系統精確統計）：\n"
        f"- 整體不良率：{this_line['defect_rate_pct']}%\n"
        f"- 逐月不良率趨勢：{trend_text}\n\n"
        f"分析要求：\n"
        f"1. 先指出數據中的『關鍵變化點』(哪個月、從多少變到多少)。\n"
        f"2. 『可能原因』必須結合上述知識庫的『標準排查順序』，"
        f"針對這個變化點推理，不要只是複述知識庫的通用條列。\n"
        f"3. 『建議行動』要對應知識庫提到的具體排查項目"
        f"(如錫膏印刷參數、鋼板、回流溫度曲線等)，要具體可執行。\n"
        f"4. 不得更動任何數字。"
    )
    return situation


if __name__ == "__main__":
    print("===== 各產線整體不良率 =====")
    for r in get_line_defect_rates():
        print(r)
    print("\n===== build_situation(LINE_B) 產出的情境 =====")
    print(build_situation("LINE_B"))