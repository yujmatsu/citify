"""倫理ガードレール: 全 agent 共通の禁止語パターン (Plan E で集約)。

PROJECT.md §5 倫理制約に基づく post-validation 用 regex パターン。
translator / relevance / concierge / 今後の agent 全てがこの単一 source を参照。

設計判断:
    - 各 agent ファイルで FORBIDDEN_PATTERNS を再定義していると、追加・修正時に
      drift する (例: translator だけ patterns 増えて relevance が古いまま)
    - LLM 出力の倫理チェックは Citify の根幹なので、変更時に全 agent に確実に
      伝わる構造が必要 → 単一 module に集約

追加方針:
    - 新パターン追加時は、本ファイルだけ修正すれば全 agent に反映
    - パターンは「明らかな違反」だけにとどめる (false positive 回避)
    - グレーゾーンは LLM 自己申告 (contains_politician_names 等) で検出
"""

from __future__ import annotations

import re

# Citify が絶対に出力してはいけないパターン (PROJECT.md §5)
FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"処方"),  # 医療診断的判断の禁止
    re.compile(r"投票.{0,5}推奨"),  # 政治的中立違反
    re.compile(r"必ず投票"),  # 同上
    re.compile(r"絶対に.{0,3}(賛成|反対)"),  # 賛否表明の禁止
]


def find_forbidden_matches(text: str) -> list[str]:
    """text に含まれる禁止パターンの正体文字列を返す (デバッグ・ログ用)。

    Args:
        text: 検査対象文字列

    Returns:
        マッチしたパターン pattern.pattern のリスト。違反なしなら空 list。
    """
    return [p.pattern for p in FORBIDDEN_PATTERNS if p.search(text)]
