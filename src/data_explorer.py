"""資料探勘模組:讀任意 CSV、自動探勘、組成 LLM 可讀的情境。
職責邊界:只負責『確定性的資料概覽』,不碰 LLM、不做解讀。
這對應整個專案的核心原則——確定性歸程式、機率性歸 LLM。
"""
from io import BytesIO
import pandas as pd
from src.vector_retriever import retrieve
from src.llm_client import analyze_dataset


def explore_dataframe(df: pd.DataFrame, max_rows_shown: int = 5) -> dict:
    """對一個 DataFrame 做基本探勘,回傳結構化的『資料概貌』。
    回傳是 dict(不是字串)——後面再決定怎麼組成文字情境,
    這樣探勘結果也能被別處(例如 API 回應)直接用。
    """
    # 1. 基本形狀:幾列幾欄
    n_rows, n_cols = df.shape

    # 2. 欄位與型別:LLM 要知道每欄是數值還文字才能建議怎麼分析
    columns_info = []
    for col in df.columns:
        columns_info.append({
            "name": col,
            "dtype": str(df[col].dtype),                  # int64 / float64 / object 等
            "n_missing": int(df[col].isna().sum()),       # 缺失值數量(資料品質訊號)
            "n_unique": int(df[col].nunique()),           # 唯一值數量(高 = 像分類欄)
        })

    # 3. 數值欄的敘述統計:平均、標準差、最大最小等(只對數值欄有意義)
    numeric_summary = {}
    numeric_cols = df.select_dtypes(include="number").columns
    if len(numeric_cols) > 0:
        # describe() 回傳一個 DataFrame,轉成 dict 方便後續處理
        desc = df[numeric_cols].describe().round(2).to_dict()
        numeric_summary = desc

    # 4. 前幾列:讓 LLM「看一眼」真實資料長相
    sample_rows = df.head(max_rows_shown).to_dict(orient="records")

    return {
        "shape": {"rows": n_rows, "cols": n_cols},
        "columns": columns_info,
        "numeric_summary": numeric_summary,
        "sample_rows": sample_rows,
    }


def build_data_situation(profile: dict) -> str:
    """把探勘結果組成『一段給 LLM 看的自然語言描述』。
    輸入是 explore_dataframe 回的 dict,輸出是字串(LLM 的 prompt 素材)。
    """
    lines = []
    lines.append(f"資料共 {profile['shape']['rows']} 列 × {profile['shape']['cols']} 欄。")
    lines.append("")
    lines.append("欄位資訊：")
    for col in profile["columns"]:
        lines.append(
            f"- {col['name']}（型別 {col['dtype']}）："
            f"{col['n_unique']} 個不同值，缺失 {col['n_missing']} 筆"
        )

    if profile["numeric_summary"]:
        lines.append("")
        lines.append("數值欄統計（前幾項代表性指標）：")
        for col_name, stats in profile["numeric_summary"].items():
            lines.append(
                f"- {col_name}：平均 {stats.get('mean')}、"
                f"最小 {stats.get('min')}、最大 {stats.get('max')}、"
                f"標準差 {stats.get('std')}"
            )

    lines.append("")
    lines.append("資料前幾列範例：")
    for i, row in enumerate(profile["sample_rows"], 1):
        lines.append(f"  第 {i} 列：{row}")

    return "\n".join(lines)


def load_csv_from_bytes(content: bytes) -> pd.DataFrame:
    """從位元組讀 CSV(這個函式為 API 接檔案上傳時用,本機測試也能用)。
    包成函式是為了之後 API 能用同一個入口,職責一致。
    """
    return pd.read_csv(BytesIO(content))


# ===== 本機測試:用你既有的 factory.db 匯出一份 CSV 來試 =====
if __name__ == "__main__":
    import sqlite3
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    # 從你的 factory.db 撈資料當測試素材(不影響原資料)
    conn = sqlite3.connect(str(PROJECT_ROOT / "factory.db"))
    df = pd.read_sql_query("SELECT * FROM production", conn)
    conn.close()

    print("===== 探勘結果(原始 dict) =====")
    profile = explore_dataframe(df)
    print(f"形狀: {profile['shape']}")
    print(f"欄位數: {len(profile['columns'])}")

    print("\n===== 組成的情境字串 =====")
    situation = build_data_situation(profile)
    print(situation)
    
    print("\n===== 用資料概貌當查詢去檢索知識庫 =====")
    # 拿欄位名當查詢素材——最能代表這份資料「是關於什麼」
    query = " ".join(c["name"] for c in profile["columns"])
    hits = retrieve(query, top_k=2)

    # 相似度門檻:夠高才用,不夠就乾脆不用(避免雜訊)
    RELEVANCE_THRESHOLD = 0.4
    relevant_hits = [h for h in hits if h["score"] >= RELEVANCE_THRESHOLD]

    if relevant_hits:
        print(f"找到 {len(relevant_hits)} 段相關知識:")
        for h in relevant_hits:
            print(f"  - {h['title']}(相似度 {h['score']})")
        kb_text = "\n\n".join(
            f"【{h['title']}】\n{h['content'].strip()}" for h in relevant_hits
        )
    else:
        print(f"檢索到的知識相似度都低於門檻 {RELEVANCE_THRESHOLD},不使用 RAG")
        kb_text = ""

    print("\n===== 跑 LLM 探勘式分析 =====")
    result = analyze_dataset(situation, kb_context=kb_text)
    print(f"\n資料概要:{result.資料概要}")
    print("\n主要觀察:")
    for x in result.主要觀察:
        print(f"  - {x}")
    print("\n分析建議:")
    for x in result.分析建議:
        print(f"  - {x}")
    print("\n資料品質警告:")
    if result.資料品質警告:
        for x in result.資料品質警告:
            print(f"  - {x}")
    else:
        print("  (無)")