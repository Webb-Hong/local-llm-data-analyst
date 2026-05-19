"""知識檢索模組(RAG 的「檢索」這一步)。
目前用最簡單的關鍵字比對。生產級會換成向量語意檢索,
但「檢索→回傳相關片段」這個介面與角色完全相同。
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_PATH = PROJECT_ROOT / "knowledge" / "defect_kb.md"


def load_kb_sections() -> list[dict]:
    """把知識庫檔案，依 markdown 的 # 標題切成一段一段。
    回傳 [{'title': '錫橋 (Solder Bridge)', 'content': '...'}, ...]
    """
    text = KB_PATH.read_text(encoding="utf-8")
    sections = []
    current = None
    for line in text.splitlines():
        if line.startswith("# "):
            if current:
                sections.append(current)
            current = {"title": line[2:].strip(), "content": ""}
        elif current is not None:
            current["content"] += line + "\n"
    if current:
        sections.append(current)
    return sections


def retrieve(query: str, top_k: int = 2) -> list[dict]:
    """從知識庫找出和 query 最相關的 top_k 段。
    最簡單的做法:看 query 裡的詞,在每段出現幾次,出現越多越相關。
    """
    sections = load_kb_sections()

    scored = []
    for sec in sections:
        haystack = sec["title"] + sec["content"]
        # 對 query 裡每個「長度>=2的字串片段」計算命中次數(極簡分詞)
        score = 0
        for token in set(query):
            if token.strip():
                score += haystack.count(token)
        scored.append((score, sec))

    # 依分數由高到低排序,取前 top_k 段
    scored.sort(key=lambda x: x[0], reverse=True)
    return [sec for score, sec in scored[:top_k] if score > 0]


if __name__ == "__main__":
    q = "SMT 產線錫橋 solder bridge 不良率上升"
    print(f"查詢：{q}\n")
    for sec in retrieve(q):
        print(f"【命中段落】{sec['title']}")
        print(sec["content"])
        print("---")