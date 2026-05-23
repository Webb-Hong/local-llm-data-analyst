"""Streamlit Demo 介面:支援產線分析(既有) + 上傳資料分析(新增)。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import streamlit as st
import requests

from src.data_explorer import explore_dataframe, build_data_situation

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="製造分析助手", layout="wide")
st.title("製造產線品質分析助手")

# ===== 用分頁切換兩種模式 =====
tab1, tab2, tab3 = st.tabs(["📊 既有產線分析", "📁 上傳資料分析", "💬 對話追問"])

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
                        # 順手算完整 situation 存起來(本機 venv 可以直接 import src)
                        uploaded.seek(0)
                        preview_df_again = pd.read_csv(uploaded)
                        profile = explore_dataframe(preview_df_again)
                        st.session_state["upload_situation"] = build_data_situation(profile)
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
                
# ========== Tab 3: 對話追問(對上傳的資料做多輪追問) ==========
with tab3:
    st.write("針對上傳的資料,以對話方式做進一步追問。")

    # 檢查:有沒有先在 Tab 2 上傳分析過?
    if "upload_result" not in st.session_state or "upload_situation" not in st.session_state:
        st.info("👈 請先到「上傳資料分析」分頁上傳 CSV 並執行分析,再來這裡追問。")
    else:
        # ===== 初始化對話歷史(只在第一次進入時做) =====
        if "chat_messages" not in st.session_state:
            st.session_state["chat_messages"] = []

        # ===== 顯示過往對話 =====
        for msg in st.session_state["chat_messages"]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # ===== 對話輸入框 =====
        user_input = st.chat_input("輸入你的問題,例如:LINE_B 為什麼不良率最高?")

        if user_input:
            # 把使用者新訊息加進歷史
            st.session_state["chat_messages"].append(
                {"role": "user", "content": user_input}
            )

            # 立刻顯示使用者剛剛打的訊息(不用等 API 回應)
            with st.chat_message("user"):
                st.write(user_input)

            # 呼叫 /chat API
            with st.chat_message("assistant"):
                with st.spinner("分析中..."):
                    try:
                        # 第一輪需要送 data_profile_text,後續送 None
                        is_first_round = len(st.session_state["chat_messages"]) == 1
                        payload = {
                            "messages": st.session_state["chat_messages"],
                            "data_profile_text": (
                                st.session_state["upload_situation"]
                                if is_first_round else None
                            ),
                            "auto_compress": True,
                        }
                        r = requests.post(
                            f"{API_BASE}/chat",
                            json=payload,
                            timeout=120,
                        )
                        if r.status_code == 200:
                            data = r.json()
                            # 把 API 回的「更新後完整歷史」覆蓋本地 session
                            st.session_state["chat_messages"] = data["updated_messages"]
                            # 顯示這輪 assistant 的最新回答
                            st.write(data["updated_messages"][-1]["content"])
                            if data["was_compressed"]:
                                st.caption("ℹ️ 對話歷史已壓縮以節省 context")
                        elif r.status_code == 503:
                            st.warning(f"服務暫時無法完成:{r.json().get('detail')}")
                        else:
                            st.error(f"分析失敗(HTTP {r.status_code}):{r.json().get('detail')}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"請求錯誤:{e}")

        # ===== 清除對話按鈕 =====
        if st.session_state["chat_messages"]:
            if st.button("🗑️ 清除對話歷史", key="btn_clear_chat"):
                st.session_state["chat_messages"] = []
                st.rerun()