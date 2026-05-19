"""Streamlit Demo 介面:呼叫 FastAPI 後端做製造分析。
架構:Streamlit(前端/呈現) --HTTP--> FastAPI(後端/分析邏輯)
"""
import streamlit as st
import requests

# 你的 API 位址。注意:這也是「設定」,理想上該用環境變數
# (呼應階段 0 學的設定分離),這裡先寫死,階段 5 容器化時會改成可配置
API_BASE = "http://localhost:8000"

st.title("製造產線品質分析助手")
st.write("選擇一條產線，系統會用 SQL 計算數據事實，再由 AI 解讀並給出建議。")

# ---- 取得可選產線清單(呼叫 API 的 GET /lines)----
try:
    resp = requests.get(f"{API_BASE}/lines", timeout=5)
    resp.raise_for_status()
    lines_data = resp.json()
    line_ids = [r["line_id"] for r in lines_data]
except requests.exceptions.RequestException as e:
    # 連不到後端時,給使用者清楚訊息,不要讓介面崩掉
    st.error(f"無法連線後端 API，請確認 FastAPI 是否啟動。錯誤：{e}")
    st.stop()  # 停止後續執行,避免一連串錯誤

# 顯示各產線目前不良率(讓使用者選之前先有概觀)
st.subheader("各產線目前不良率")
for r in lines_data:
    st.write(f"- {r['line_id']}：{r['defect_rate_pct']}%")

# ---- 選產線 + 觸發分析 ----
selected = st.selectbox("選擇要分析的產線", line_ids)

if st.button("執行 AI 分析"):
    # 只有「按下按鈕這次重跑」會進到這裡 → 昂貴的 API 呼叫只觸發一次
    with st.spinner("分析中（AI 解讀需要十幾秒，請稍候）..."):
        try:
            r = requests.post(
                f"{API_BASE}/diagnosis",
                json={"line_id": selected},
                timeout=60,  # LLM 慢,逾時要設長一點
            )
            if r.status_code == 200:
                # 成功:把結果存進 session_state(跨重跑保留)
                st.session_state["result"] = r.json()
                st.session_state["analyzed_line"] = selected
            elif r.status_code == 404:
                st.error(f"找不到該產線：{r.json().get('detail')}")
            elif r.status_code == 503:
                # 對應你階段 3 設計的 503:可重試
                st.warning(f"服務暫時無法完成：{r.json().get('detail')}")
            else:
                st.error(f"分析失敗（HTTP {r.status_code}）：{r.json().get('detail')}")
        except requests.exceptions.Timeout:
            st.error("分析逾時，請稍後再試。")
        except requests.exceptions.RequestException as e:
            st.error(f"請求發生錯誤：{e}")

# ---- 顯示結果(從 session_state 讀,所以重跑也不會消失)----
if "result" in st.session_state:
    res = st.session_state["result"]
    st.divider()
    st.subheader(f"分析結果：{st.session_state['analyzed_line']}")

    # 嚴重程度用顏色標示,提升可讀性(呼應 JD「呈現優化」)
    sev = res["嚴重程度"]
    color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(sev, "⚪")
    st.write(f"**嚴重程度：** {color} {sev}")

    st.write("**可能原因：**")
    for x in res["可能原因"]:
        st.write(f"- {x}")

    st.write("**建議行動：**")
    for x in res["建議行動"]:
        st.write(f"- {x}")

    st.write("**需要補充的資訊：**")
    for x in res["需要補充的資訊"]:
        st.write(f"- {x}")