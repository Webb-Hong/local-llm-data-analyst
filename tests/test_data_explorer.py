"""測試 data_explorer 模組——pandas 資料探勘邏輯。

技術重點:
- 用 pd.DataFrame({...}) 直接造測試資料(不用 fixture 也行,但統一管理較好)
- 用 fixture 提供多種 DataFrame 場景(基本/僅數值/僅類別/有缺失值)
- 測試結構性(回傳 dict 形狀)和值性(計算結果正確)分開
- group_summaries 的測試特別重要——這是階段 6-1A 才加的功能
"""
import pandas as pd
import pytest
from src.data_explorer import explore_dataframe, build_data_situation


# ===== Fixtures:各種測試用 DataFrame =====


@pytest.fixture
def basic_df():
    """基本的混合型別 DataFrame:類別欄 + 數值欄。
    
    line_id 是類別欄(3 個唯一值),output 和 defects 是數值欄。
    這個 fixture 模仿 factory.db 的 schema,測試最常見場景。
    """
    return pd.DataFrame({
        "line_id": ["A", "A", "B", "B", "C"],
        "output": [100, 200, 150, 250, 300],
        "defects": [1, 4, 3, 7, 6],
    })


@pytest.fixture
def numeric_only_df():
    """只有數值欄、沒有類別欄。"""
    return pd.DataFrame({
        "x": [1.0, 2.0, 3.0, 4.0],
        "y": [10.0, 20.0, 30.0, 40.0],
    })


@pytest.fixture
def with_missing_df():
    """含缺失值的 DataFrame——驗證 n_missing 邏輯。"""
    return pd.DataFrame({
        "category": ["X", "Y", None, "X", None],
        "value": [1.0, None, 3.0, 4.0, 5.0],
    })


# ===== explore_dataframe:基本結構測試 =====


def test_explore_returns_dict(basic_df):
    """應該回傳 dict,不是其他型別。"""
    result = explore_dataframe(basic_df)
    assert isinstance(result, dict)


def test_explore_has_required_keys(basic_df):
    """回傳的 dict 應該包含所有預期 key——這是函式的契約。"""
    result = explore_dataframe(basic_df)
    
    required_keys = {"shape", "columns", "numeric_summary", "sample_rows", "group_summaries"}
    assert required_keys.issubset(set(result.keys()))


# ===== shape 測試 =====


def test_explore_shape_correct(basic_df):
    """shape 應該正確反映 DataFrame 大小。
    
    basic_df 有 5 列 3 欄。
    """
    result = explore_dataframe(basic_df)
    
    assert result["shape"]["rows"] == 5
    assert result["shape"]["cols"] == 3


# ===== columns 資訊測試 =====


def test_explore_columns_count_matches_df(basic_df):
    """columns 數量應該等於 DataFrame 欄數。"""
    result = explore_dataframe(basic_df)
    
    assert len(result["columns"]) == 3


def test_explore_columns_have_required_fields(basic_df):
    """每個欄資訊應該包含 name、dtype、n_missing、n_unique。"""
    result = explore_dataframe(basic_df)
    
    for col_info in result["columns"]:
        assert "name" in col_info
        assert "dtype" in col_info
        assert "n_missing" in col_info
        assert "n_unique" in col_info


def test_explore_n_unique_correct(basic_df):
    """n_unique 應該正確算出唯一值數量。
    
    line_id: A/B/C 三個唯一值
    output: 5 個唯一值(100/200/150/250/300)
    """
    result = explore_dataframe(basic_df)
    
    cols_by_name = {c["name"]: c for c in result["columns"]}
    
    assert cols_by_name["line_id"]["n_unique"] == 3
    assert cols_by_name["output"]["n_unique"] == 5


def test_explore_n_missing_correct(with_missing_df):
    """n_missing 應該正確算出缺失值數量。
    
    category 有 2 個 None
    value 有 1 個 None
    """
    result = explore_dataframe(with_missing_df)
    
    cols_by_name = {c["name"]: c for c in result["columns"]}
    
    assert cols_by_name["category"]["n_missing"] == 2
    assert cols_by_name["value"]["n_missing"] == 1


# ===== numeric_summary 測試 =====


def test_explore_numeric_summary_only_has_numeric_columns(basic_df):
    """numeric_summary 只該包含數值欄,不該有 line_id(類別欄)。"""
    result = explore_dataframe(basic_df)
    
    summary_cols = set(result["numeric_summary"].keys())
    
    assert "output" in summary_cols
    assert "defects" in summary_cols
    assert "line_id" not in summary_cols   # 類別欄不該出現


def test_explore_numeric_summary_values_correct(basic_df):
    """數值欄的統計值應該正確。
    
    output = [100, 200, 150, 250, 300]
    mean = 200, min = 100, max = 300
    """
    result = explore_dataframe(basic_df)
    
    output_stats = result["numeric_summary"]["output"]
    
    assert output_stats["mean"] == pytest.approx(200.0)
    assert output_stats["min"] == pytest.approx(100.0)
    assert output_stats["max"] == pytest.approx(300.0)


def test_explore_no_numeric_summary_when_no_numeric_columns():
    """如果沒有數值欄,numeric_summary 應該是空 dict。"""
    pure_categorical_df = pd.DataFrame({
        "color": ["red", "blue", "green"],
        "size": ["S", "M", "L"],
    })
    
    result = explore_dataframe(pure_categorical_df)
    
    assert result["numeric_summary"] == {}


# ===== sample_rows 測試 =====


def test_explore_sample_rows_respects_max_rows(basic_df):
    """sample_rows 應該不超過 max_rows_shown 限制。"""
    # basic_df 有 5 列,要求只看 3 列
    result = explore_dataframe(basic_df, max_rows_shown=3)
    
    assert len(result["sample_rows"]) == 3


def test_explore_sample_rows_default_is_5(basic_df):
    """預設 max_rows_shown=5——basic_df 剛好 5 列,所以全拿。"""
    result = explore_dataframe(basic_df)
    
    assert len(result["sample_rows"]) == 5


def test_explore_sample_rows_are_dicts(basic_df):
    """每列應該是 dict(由 to_dict(orient='records') 產生)。"""
    result = explore_dataframe(basic_df)
    
    for row in result["sample_rows"]:
        assert isinstance(row, dict)
        # 每列應該包含所有欄位
        assert "line_id" in row
        assert "output" in row


# ===== group_summaries 測試(階段 6-1A 加的功能,重點測試) =====


def test_explore_group_summaries_detects_categorical_column(basic_df):
    """類別欄應該被偵測並產生 group_summaries。
    
    line_id 有 3 個唯一值且型別 object,應該被當類別欄。
    """
    result = explore_dataframe(basic_df)
    
    assert "line_id" in result["group_summaries"]


def test_explore_group_summaries_values_correct(basic_df):
    """分組統計的值應該正確。
    
    LINE_A: output=[100,200], defects=[1,4] → mean output=150, mean defects=2.5
    LINE_B: output=[150,250], defects=[3,7] → mean output=200, mean defects=5.0
    LINE_C: output=[300], defects=[6] → mean output=300, mean defects=6.0
    """
    result = explore_dataframe(basic_df)
    
    groups = result["group_summaries"]["line_id"]
    
    assert groups["A"]["output"] == pytest.approx(150.0)
    assert groups["A"]["defects"] == pytest.approx(2.5)
    assert groups["B"]["output"] == pytest.approx(200.0)
    assert groups["B"]["defects"] == pytest.approx(5.0)
    assert groups["C"]["output"] == pytest.approx(300.0)


def test_explore_no_group_summaries_when_no_categorical(numeric_only_df):
    """純數值的 DataFrame 應該沒有 group_summaries(因為沒類別欄)。"""
    result = explore_dataframe(numeric_only_df)
    
    assert result["group_summaries"] == {}


def test_explore_numeric_column_not_treated_as_categorical():
    """『唯一值少的數值欄』不該被當類別欄。
    
    例如 output=[1, 2, 3, 4, 5] 只有 5 個唯一值,
    但因為它是 int64(數值型),不該被當類別欄做 group by。
    這驗證了 'not in numeric_col_names' 的防呆設計。
    """
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],   # 5 個唯一值的 int
        "value": [10.0, 20.0, 30.0, 40.0, 50.0],
    })
    
    result = explore_dataframe(df)
    
    # 雖然 id 唯一值少,但因為是數值欄,不該變類別欄
    assert "id" not in result["group_summaries"]


# ===== build_data_situation 測試 =====


def test_build_data_situation_returns_string(basic_df):
    """build_data_situation 應該回傳字串。"""
    profile = explore_dataframe(basic_df)
    result = build_data_situation(profile)
    
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_data_situation_contains_shape(basic_df):
    """情境字串應該包含 shape 資訊。"""
    profile = explore_dataframe(basic_df)
    result = build_data_situation(profile)
    
    # 5 列 3 欄 應該在字串裡看得到
    assert "5" in result
    assert "3" in result


def test_build_data_situation_contains_column_names(basic_df):
    """情境字串應該列出所有欄位名。"""
    profile = explore_dataframe(basic_df)
    result = build_data_situation(profile)
    
    assert "line_id" in result
    assert "output" in result
    assert "defects" in result


def test_build_data_situation_includes_group_summaries(basic_df):
    """有類別欄時,情境字串應該包含分組統計區塊。"""
    profile = explore_dataframe(basic_df)
    result = build_data_situation(profile)
    
    # 確認分組統計區塊存在
    assert "分組" in result
    # 確認個別類別被列出
    assert "A" in result and "B" in result and "C" in result


def test_build_data_situation_skips_group_summaries_when_empty(numeric_only_df):
    """純數值資料時,字串不該有「分組」這個區塊。"""
    profile = explore_dataframe(numeric_only_df)
    result = build_data_situation(profile)
    
    # 純數值資料沒類別欄,所以分組統計區塊不該被加入
    assert "分組" not in result