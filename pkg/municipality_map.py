"""tenant_id ↔ municipality_code のマッピング (DiscussNet kaigiroku.net 系)。

出典: `infra/seed/tier1_supplements.csv` (tier 1 の DiscussNet 採用 tenant)

将来の整理:
    - CSV ローダー化して seed から自動構築
    - 国会 (00000) や voices_asp など他系列も統合
"""

from __future__ import annotations

# kaigiroku.net (DiscussNet) tenant_id → 5 桁自治体コード
KAIGIROKU_TENANT_TO_MUNI_CODE: dict[str, str] = {
    "shinjuku": "13104",
    "sumida": "13107",
    "arakawa": "13118",
    "yokohama": "14100",
    "prefosaka": "27000",
    "cityosaka": "27100",
    "prefokayama": "33000",
    "tosa": "39000",  # tier1_supplements.csv 準拠 (本来は 39205 だが seed が 39000)
    "prefoita": "44000",
}

# 国会 (national diet)
NATIONAL_DIET_CODE = "00000"


def resolve_municipality_code(source: str, tenant_id: str | None) -> str:
    """source + tenant_id から municipality_code を解決。

    Args:
        source: メッセージ source (例: 'kaigiroku_net', 'kokkai_api', 'press_rss')
        tenant_id: source 依存。
            - kaigiroku_net: テナント文字列 (例: 'yokohama')
            - press_rss: 5 桁自治体コードを直接渡す (例: '13000' = 東京都)

    Returns:
        5 桁自治体コード。マップに無い場合は '00000' (国会扱い fallback)
    """
    if source == "kokkai_api":
        return NATIONAL_DIET_CODE
    if source == "kaigiroku_net" and tenant_id:
        return KAIGIROKU_TENANT_TO_MUNI_CODE.get(tenant_id, NATIONAL_DIET_CODE)
    if source == "press_rss" and tenant_id:
        # press_rss は publish 時に tenant_id へ 5 桁コードを直接設定する規約 (B-7)
        if tenant_id.isdigit() and len(tenant_id) == 5:
            return tenant_id
        return NATIONAL_DIET_CODE
    return NATIONAL_DIET_CODE
