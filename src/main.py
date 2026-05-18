"""主流程：把『SQL 數據事實』接給『LLM 解讀+Pydantic 驗證』。
這支檔案展示整條鏈：資料 → 計算 → 解讀 → 驗證。
"""
from src.analyzer import build_situation, get_line_defect_rates
from src.llm_client import analyze_validated


def diagnose_line(line_id: str):
    # ① 確定性：SQL 算出數據事實，組成情境
    situation = build_situation(line_id)
    print(f"===== 餵給 LLM 的情境（數字來自 SQL）=====\n{situation}\n")

    # ② 機率性：LLM 解讀；③ 確定性：Pydantic 驗證(analyze_validated 內含)
    result = analyze_validated(situation)

    # 印出經過驗證的結構化結果
    print(f"===== {line_id} 分析結果（已通過驗證）=====")
    print("嚴重程度：", result.嚴重程度)
    print("可能原因：")
    for x in result.可能原因:
        print("  -", x)
    print("建議行動：")
    for x in result.建議行動:
        print("  -", x)
    print("需要補充的資訊：")
    for x in result.需要補充的資訊:
        print("  -", x)
    return result


if __name__ == "__main__":
    # 先看哪條線最嚴重，再針對它做深入診斷
    print("=== 各產線不良率總覽 ===")
    for r in get_line_defect_rates():
        print(f'  {r["line_id"]}: {r["defect_rate_pct"]}%')
    print()

    diagnose_line("LINE_B")   # LINE_B 是有問題那條