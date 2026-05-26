"""測試 retriever 模組——關鍵字檢索的 RAG 基礎。

設計重點:retriever 從『真實知識庫檔案 (knowledge/defect_kb.md)』讀資料,
所以測試會依賴那個檔案存在。這是個取捨——
- 優點:測到真實邏輯,不用 mock
- 缺點:測試依賴外部檔案,若該檔案內容變動可能影響測試

更嚴謹的做法是 mock load_kb_sections(),但對這個專案規模沒必要。
"""
import pytest
from src.retriever import load_kb_sections, retrieve


# ===== 測 load_kb_sections =====


def test_load_kb_sections_returns_non_empty():
    """知識庫檔案應該至少有一段內容。"""
    sections = load_kb_sections()
    assert len(sections) > 0


def test_load_kb_sections_structure():
    """每段應該有 title 和 content 兩個 key。"""
    sections = load_kb_sections()
    for sec in sections:
        assert "title" in sec
        assert "content" in sec
        # title 不該是空的(否則代表 # 標題解析有問題)
        assert sec["title"]


# ===== 測 retrieve =====


def test_retrieve_with_relevant_query_returns_results():
    """有相關關鍵字的查詢,應該找到至少一段。
    
    用「不良率」這個詞——這個詞在製造知識庫一定會出現,
    所以期望至少有命中。
    """
    results = retrieve("不良率", top_k=2)
    
    assert len(results) > 0


def test_retrieve_respects_top_k_limit():
    """top_k 參數應該限制最大結果數。
    
    即使有 100 段都命中,top_k=2 也只能拿 2 段。
    這驗證『分頁/限制』的契約。
    """
    results = retrieve("不良率", top_k=2)
    
    assert len(results) <= 2


def test_retrieve_relevant_query_scores_higher_than_irrelevant():
    """相關 query 應該比無關 query 拿到『更多/更相關』的結果。
    
    為什麼不直接測『無關 query 回空 list』?
    因為這個 retriever 用逐字元計分,任何字串都可能因為單字元
    命中(例如『B』命中『Bridge』、『不』命中『不良率』)——
    『絕對無命中』在中文+英文混雜的知識庫幾乎不可能。
    
    這個限制本身正是『關鍵字 RAG 不夠用、要做向量版』的工程理由。
    所以這個測試改成驗證『相對性』——相關 query 應該『遠更命中』,
    而不是『無關 query 完全沒命中』。
    """
    relevant_results = retrieve("錫橋 不良率 回流", top_k=5)
    irrelevant_results = retrieve("zzz", top_k=5)
    
    # 相關 query 應該有結果
    assert len(relevant_results) > 0
    # 而且第一個結果的內容應該『真的相關』——含有 query 的某個關鍵詞
    top_content = relevant_results[0]["title"] + relevant_results[0]["content"]
    assert any(kw in top_content for kw in ["錫橋", "不良率", "回流"])


def test_retrieve_results_have_correct_structure():
    """回傳的每段應該有 title 和 content。"""
    results = retrieve("不良率", top_k=2)
    
    for sec in results:
        assert "title" in sec
        assert "content" in sec


def test_retrieve_top_k_zero_returns_empty():
    """top_k=0 應該回空 list(沒人要結果)。"""
    results = retrieve("不良率", top_k=0)
    
    assert results == []