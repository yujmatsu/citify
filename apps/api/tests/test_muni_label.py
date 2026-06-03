"""_muni_label の表示名解決テスト (朝霞市 11227 が '自治体11227' に化けない回帰防止)。"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _stub_firestore_module() -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]
        stub.Increment = MagicMock()  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


def _reset_name_cache() -> None:
    from apps.api import main as api_main

    api_main._MUNI_NAME_CACHE = None


def test_hardcoded_codes_take_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """国会/都道府県はハードコードで即解決 (BQ を引かない)。"""
    from apps.api import main as api_main

    _reset_name_cache()
    # BQ が呼ばれたら失敗させる — ハードコードで解決されるはず
    monkeypatch.setattr(
        api_main, "_load_all_muni_names", lambda: pytest.fail("BQ should not be queried")
    )
    assert api_main._muni_label("00000") == "国会"
    assert api_main._muni_label("13000") == "東京都"


def test_resolves_name_from_municipality_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    """ハードコード未登録 (朝霞市 11227) は municipality_stats の名前で解決。"""
    from apps.api import main as api_main

    _reset_name_cache()
    monkeypatch.setattr(api_main, "_load_all_muni_names", lambda: {"11227": "朝霞市"})
    assert api_main._muni_label("11227") == "朝霞市"


def test_falls_back_to_code_when_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """ハードコードにも BQ にも無いコードは `自治体{code}`。"""
    from apps.api import main as api_main

    _reset_name_cache()
    monkeypatch.setattr(api_main, "_load_all_muni_names", lambda: {})
    assert api_main._muni_label("99999") == "自治体99999"


def test_load_all_muni_names_graceful_on_bq_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """BQ 失敗時は空 dict で graceful (例外を投げない)。"""
    from apps.api import main as api_main

    _reset_name_cache()
    mock_client = MagicMock()
    mock_client.query.side_effect = RuntimeError("BQ down")
    monkeypatch.setattr(api_main, "_get_bq_client", lambda: mock_client)
    assert api_main._load_all_muni_names() == {}
    # フォールバックも動く
    assert api_main._muni_label("11227") == "自治体11227"


def test_load_all_muni_names_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """2 回目は BQ を再クエリしない (キャッシュ)。"""
    from apps.api import main as api_main

    _reset_name_cache()
    mock_client = MagicMock()
    rows = [{"municipality_code": "11227", "municipality_name": "朝霞市"}]
    mock_client.query.return_value.result.return_value = iter(rows)
    monkeypatch.setattr(api_main, "_get_bq_client", lambda: mock_client)

    assert api_main._load_all_muni_names() == {"11227": "朝霞市"}
    api_main._load_all_muni_names()  # 2 回目
    mock_client.query.assert_called_once()  # クエリは 1 回だけ
