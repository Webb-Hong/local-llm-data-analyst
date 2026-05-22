"""Streamlit Demo 介面:支援產線分析(既有) + 上傳資料分析(新增)。"""
import os
import streamlit as st
import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="製造分析助手", layout="wide")
st.title("製造產線品質分析助手")

st.write("NEW VERSION v2 - tabs version")

# ===== 用分頁切換兩種模式 =====
tab1, tab2 = st.tabs(["📊 既有產線分析", "📁 上傳資料分析"])


# ========== Tab 1: 既有產線分析(你原本的程式碼搬進來) ==========
with tab1:
    st.write("選擇一條既有產線,系統會用 SQL 計算數據事實、AI 解讀並給建議。")

    try:
        resp = requests.get(f"{API_BASE}/lines", timeout=5)
        resp.raise_for_status()
        lines_data = resp.json()
        line_ids = [r["line_id"] for r in lines_data]
    except requests.exceptions.RequestException as e:
        st.error(f"無法連線後端 API,請確認 FastAPI 是否啟動。錯誤:{e}")
        st.stop()

    st.subheader("各產線目前不良率")
    for r in lines_data:
        st.write(f"- {r['line_id']}:{r['defect_rate_pct']}%")

    selected = st.selectbox("選擇要分析的產線", line_ids)

    if st.button("執行 AI 分析", key="btn_line"):
        with st.spinner("分析中(AI 解讀需要十幾秒,請稍候)..."):
            try:
                r = requests.post(
                    f"{API_BASE}/diagnosis",
                    json={"line_id": selected},
                    timeout=60,
                )
                if r.status_code == 200:
                    st.session_state["line_result"] = r.json()
                    st.session_state["analyzed_line"] = selected
                elif r.status_code == 503:
                    st.warning(f"服務暫時無法完成:{r.json().get('detail')}")
                else:
                    st.error(f"分析失敗(HTTP {r.status_code}):{r.json().get('detail')}")
            except requests.exceptions.RequestException as e:
                st.error(f"請求錯誤:{e}")

    if "line_result" in st.session_state:
        res = st.session_state["line_result"]
        st.divider()
        st.subheader(f"分析結果:{st.session_state['analyzed_line']}")
        sev = res["嚴重程度"]
        color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(sev, "⚪")
        st.write(f"**嚴重程度:** {color} {sev}")
        st.write("**可能原因:**")
        for x in res["可能原因"]:
            st.write(f"- {x}")
        st.write("**建議行動:**")
        for x in res["建議行動"]:
            st.write(f"- {x}")
        st.write("**需要補充的資訊:**")
        for x in res["需要補充的資訊"]:
            st.write(f"- {x}")


# ========== Tab 2: 上傳資料分析(新功能) ==========
with tab2:
    st.write("上傳任意 CSV 檔案,系統會自動探勘並用 AI 給分析建議。")
    st.caption("⚠️ 檔案大小上限 10 MB,僅接受 .csv 格式。")

    uploaded = st.file_uploader("選擇 CSV 檔案", type=["csv"])

    if uploaded is not None:
        # 先讓使用者看到上傳了什麼(預覽 5 列)——這是好 UX
        import pandas as pd
        try:
            preview_df = pd.read_csv(uploaded)
            st.success(f"已上傳:{uploaded.name}({preview_df.shape[0]} 列 × {preview_df.shape[1]} 欄)")
            with st.expander("📋 資料預覽(前 5 列)"):
                st.dataframe(preview_df.head())
            # 重要:預覽完要把指標 reset,不然之後 send 出去檔案會是空的
            uploaded.seek(0)
        except Exception as e:
            st.error(f"無法預覽 CSV:{e}")
            st.stop()

        if st.button("執行 AI 分析", key="btn_upload"):
            with st.spinner("分析中(AI 解讀需要十幾秒,請稍候)..."):
                try:
                    # 注意:這次用 files= 而不是 json=,因為是 multipart 上傳
                    files = {"file": (uploaded.name, uploaded.getvalue(), "text/csv")}
                    r = requests.post(
                        f"{API_BASE}/upload-and-analyze",
                        files=files,
                        timeout=120,
                    )
                    if r.status_code == 200:
                        st.session_state["upload_result"] = r.json()
                    elif r.status_code == 400:
                        st.error(f"檔案問題:{r.json().get('detail')}")
                    elif r.status_code == 413:
                        st.error(f"檔案過大:{r.json().get('detail')}")
                    elif r.status_code == 503:
                        st.warning(f"服務暫時無法完成:{r.json().get('detail')}")
                    else:
                        st.error(f"分析失敗(HTTP {r.status_code}):{r.json().get('detail')}")
                except requests.exceptions.RequestException as e:
                    st.error(f"請求錯誤:{e}")

    # 顯示上傳分析結果(從 session_state 讀)
    if "upload_result" in st.session_state:
        res = st.session_state["upload_result"]
        st.divider()
        st.subheader("📊 分析結果")

        st.markdown(f"**資料概要:** {res['資料概要']}")

        st.markdown("**主要觀察:**")
        for x in res["主要觀察"]:
            st.write(f"- {x}")

        st.markdown("**分析建議:**")
        for x in res["分析建議"]:
            st.write(f"- {x}")

        if res["資料品質警告"]:
            st.markdown("**⚠️ 資料品質警告:**")
            for x in res["資料品質警告"]:
                st.warning(x)