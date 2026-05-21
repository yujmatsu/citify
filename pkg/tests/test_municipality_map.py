"""pkg.municipality_map のテスト。"""

from __future__ import annotations

from pkg.municipality_map import (
    KAIGIROKU_TENANT_TO_MUNI_CODE,
    NATIONAL_DIET_CODE,
    resolve_municipality_code,
)


def test_kokkai_api_returns_national_diet_code():
    assert resolve_municipality_code("kokkai_api", None) == NATIONAL_DIET_CODE
    assert resolve_municipality_code("kokkai_api", "ignored") == NATIONAL_DIET_CODE


def test_kaigiroku_known_tenants():
    assert resolve_municipality_code("kaigiroku_net", "prefokayama") == "33000"
    assert resolve_municipality_code("kaigiroku_net", "yokohama") == "14100"
    assert resolve_municipality_code("kaigiroku_net", "arakawa") == "13118"
    assert resolve_municipality_code("kaigiroku_net", "cityosaka") == "27100"


def test_kaigiroku_unknown_tenant_fallbacks_to_national():
    assert resolve_municipality_code("kaigiroku_net", "unknown_xxx") == NATIONAL_DIET_CODE


def test_kaigiroku_no_tenant_fallbacks_to_national():
    assert resolve_municipality_code("kaigiroku_net", None) == NATIONAL_DIET_CODE
    assert resolve_municipality_code("kaigiroku_net", "") == NATIONAL_DIET_CODE


def test_unknown_source_fallbacks_to_national():
    assert resolve_municipality_code("press_rss", "anything") == NATIONAL_DIET_CODE


def test_tenant_map_includes_expected_tier1_tenants():
    """tier1_supplements.csv から期待される全テナントが登録されていること。"""
    expected = {"shinjuku", "sumida", "arakawa", "yokohama", "cityosaka", "prefokayama", "tosa"}
    assert expected.issubset(KAIGIROKU_TENANT_TO_MUNI_CODE.keys())
