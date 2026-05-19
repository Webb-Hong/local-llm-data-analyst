"""向量語意檢索(工業級 RAG 的「檢索」)。
用 Ollama 的 embedding 模型把文字轉成向量,
以餘弦相似度衡量語意相近程度。
介面與 retriever.retrieve() 相同,只是內部從關鍵字比對換成向量語意比對。
"""
import math
from openai import OpenAI
from src.retriever import load_kb_sections   # 切塊邏輯沿用,不重寫

# 沿用你階段 0 的本地 Ollama 連線(免費、資料不出本機)
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

EMBED_MODEL = "nomic-embed-text"


def embed(text: str) -> list[float]:
    """把一段文字轉成向量(一串數字)。"""
    resp = client.embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """餘弦相似度 = 點積 / (各自長度相乘)。
    對應你學的公式:(A·B) / (||A|| ||B||)
    """
    dot = sum(x * y for x, y in zip(a, b))          # 分子:點積 A·B
    norm_a = math.sqrt(sum(x * x for x in a))        # ||A||
    norm_b = math.sqrt(sum(y * y for y in b))        # ||B||
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ===== 事前準備:啟動時把知識庫每段都算好向量,存在記憶體 =====
# (真實系統會存進向量資料庫;此處用記憶體,原理完全相同)
_KB_CACHE = None

def _build_kb_index():
    """把知識庫每段算好向量,只做一次。"""
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE
    sections = load_kb_sections()
    for sec in sections:
        # 用「標題+內容」一起算向量,語意較完整
        sec["vector"] = embed(sec["title"] + "\n" + sec["content"])
    _KB_CACHE = sections
    return _KB_CACHE


def retrieve(query: str, top_k: int = 2) -> list[dict]:
    """向量語意檢索。介面與 retriever.retrieve() 完全相同。"""
    kb = _build_kb_index()
    query_vec = embed(query)                          # 查詢也轉成向量

    scored = []
    for sec in kb:
        sim = cosine_similarity(query_vec, sec["vector"])
        scored.append((sim, sec))

    scored.sort(key=lambda x: x[0], reverse=True)     # 相似度高→低
    # 回傳前 top_k 段(附上相似度分數,方便觀察)
    results = []
    for sim, sec in scored[:top_k]:
        results.append({
            "title": sec["title"],
            "content": sec["content"],
            "score": round(sim, 4),
        })
    return results


if __name__ == "__main__":
    # ===== 關鍵對照實驗:故意用「沒有字面命中」的查詢 =====
    from src.retriever import retrieve as keyword_retrieve

    # 這個查詢「沒有錫橋兩個字」,但語意就是在講錫橋
    query = "adjacent pads accidentally connected by excess metal"
    print(f"查詢：{query}")
    print("（注意：查詢裡沒有「錫橋」這兩個字）\n")

    print("===== 關鍵字檢索 (retriever.py) =====")
    kw = keyword_retrieve(query, top_k=2)
    if kw:
        for s in kw:
            print(f"  命中：{s['title']}")
    else:
        print("  ⚠️ 沒有命中任何段落（關鍵字比對失敗）")

    print("\n===== 向量語意檢索 (vector_retriever.py) =====")
    vec = retrieve(query, top_k=2)
    for s in vec:
        print(f"  命中：{s['title']}（相似度 {s['score']}）")