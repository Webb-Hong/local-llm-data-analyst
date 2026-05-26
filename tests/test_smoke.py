"""Smoke test:驗證 pytest 環境本身能跑。
這個檔案測的不是專案邏輯,是『我的測試環境設定對不對』。
跑得起來代表 pytest、venv、import 路徑都對,可以開始寫真實測試。
"""


def test_pytest_works():
    """最簡單的測試:1 + 1 = 2。能 pass 代表 pytest 真的能跑。"""
    assert 1 + 1 == 2


def test_can_import_project_code():
    """確認 pytest 能 import 到 src 套件——這是寫真實測試的前提。
    如果這個失敗,後面所有測試都會撞 import 錯。
    """
    from src.analyzer import get_line_defect_rates
    # 不實際呼叫,只確認 import 成功
    assert get_line_defect_rates is not None