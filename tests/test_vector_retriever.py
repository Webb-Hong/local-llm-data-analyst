"""測試 vector_retriever 模組的數學基礎(cosine_similarity)。

這個檔案測的是『純函式 + 數學運算』——沒有外部依賴、輸出可預測,
是寫 pytest 入門的最佳對象。每個測試都用 AAA pattern:
  Arrange(準備輸入)→ Act(呼叫函式)→ Assert(斷言結果)。
"""
import pytest
from src.vector_retriever import cosine_similarity


# ===== 基本數學性質測試 =====


def test_identical_vectors_return_one():
    """兩個完全相同的向量,餘弦相似度應該是 1.0(完美對齊)。"""
    # Arrange
    vec = [1.0, 2.0, 3.0]
    # Act
    result = cosine_similarity(vec, vec)
    # Assert
    # 用 pytest.approx 處理浮點數比較,因為 sqrt 等運算會有微小誤差
    assert result == pytest.approx(1.0)


def test_opposite_vectors_return_negative_one():
    """兩個完全相反方向的向量,餘弦相似度應該是 -1.0(完美反向)。"""
    vec_a = [1.0, 2.0, 3.0]
    vec_b = [-1.0, -2.0, -3.0]
    
    result = cosine_similarity(vec_a, vec_b)
    
    assert result == pytest.approx(-1.0)


def test_orthogonal_vectors_return_zero():
    """兩個垂直(正交)的向量,餘弦相似度應該是 0.0(語意無關)。"""
    # x 軸 vs y 軸,典型的正交例子
    vec_a = [1.0, 0.0]
    vec_b = [0.0, 1.0]
    
    result = cosine_similarity(vec_a, vec_b)
    
    assert result == pytest.approx(0.0)


def test_45_degree_angle_returns_sqrt_half():
    """45 度夾角的向量,餘弦值應該是 √2/2 ≈ 0.7071。
    這是一般情況的數值正確性驗證——不是 0、1、-1 這種邊界。
    """
    vec_a = [1.0, 0.0]
    vec_b = [1.0, 1.0]
    
    result = cosine_similarity(vec_a, vec_b)
    
    # √2/2 ≈ 0.7071,允許一點浮點誤差
    assert result == pytest.approx(0.7071, abs=1e-4)


# ===== 「長度不影響結果」的關鍵性質測試(這題面試會問) =====


def test_length_does_not_affect_similarity():
    """同方向但長度不同的向量,相似度仍然是 1.0。
    這驗證了餘弦相似度的核心特性:『方向才是語意,長度是雜訊』。
    對應面試金句:『文字 embedding 用方向才穩定』。
    """
    short_vec = [1.0, 1.0, 1.0]
    long_vec = [100.0, 100.0, 100.0]
    
    result = cosine_similarity(short_vec, long_vec)
    
    # 兩個向量方向完全相同(都是 (1,1,1) 方向),長度差 100 倍也不影響
    assert result == pytest.approx(1.0)


# ===== 邊界條件測試 =====


def test_zero_vector_returns_zero_not_error():
    """遇到零向量時,函式回傳 0.0 而不是 raise ZeroDivisionError。
    這驗證了實作的『工程取捨』:用 0.0 表達『無意義/無相關』,
    讓呼叫端不用處理例外。這個契約必須被測試守住。
    """
    zero_vec = [0.0, 0.0, 0.0]
    normal_vec = [1.0, 2.0, 3.0]
    
    # 兩種情境都該回 0.0,不該炸
    result_left_zero = cosine_similarity(zero_vec, normal_vec)
    result_right_zero = cosine_similarity(normal_vec, zero_vec)
    result_both_zero = cosine_similarity(zero_vec, zero_vec)
    
    assert result_left_zero == 0.0
    assert result_right_zero == 0.0
    assert result_both_zero == 0.0


# ===== Parametrize:用一支測試一次測多個案例(進階寫法) =====


@pytest.mark.parametrize("vec_a, vec_b, expected", [
    # 自己的 dot product = 平方和,跟 norm² 一樣大,所以相除剛好是 1
    ([3.0, 4.0], [3.0, 4.0], 1.0),
    # 反向
    ([3.0, 4.0], [-3.0, -4.0], -1.0),
    # 正交
    ([1.0, 0.0], [0.0, 5.0], 0.0),
    # 同方向不同長度
    ([2.0, 0.0], [10.0, 0.0], 1.0),
])
def test_cosine_various_cases(vec_a, vec_b, expected):
    """用 parametrize 一次測多個案例。
    
    @pytest.mark.parametrize 把同一個測試函式套用到多組輸入。
    比 4 個獨立 def test_xxx 更乾淨,適合『同一邏輯、不同輸入』的批量驗證。
    pytest 會把每組案例當成獨立測試,失敗時清楚指出『哪一組壞了』。
    """
    result = cosine_similarity(vec_a, vec_b)
    assert result == pytest.approx(expected)