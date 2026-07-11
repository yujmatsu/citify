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


# ---------------------------------------------------------------------------
# 政治家名 / 政党名 leak 検出 (PROJECT.md §5)
#
# FORBIDDEN_PATTERNS は「賛否表明・投票推奨」等の *スタンス* を捕捉するが、
# 政党名・政治家個人名の混入は別クラスの違反。元は timeline agent 専用だった
# パターンを本 module に集約し、生テキストを扱う translator / relevance /
# concierge / watcher からも参照できるようにする (審査対応の穴埋め、2026-07)。
#
# 注意: 個人名の網羅は原理的に不可能。本フィルタの狙いは
#   (1) 主要政党名の確実な捕捉、(2) 「氏名+役職」形の高確度な捕捉
# であり、未知の個人名漏れは「AI が賛否を判断せず事実提示に留める + 原典リンク併記」
# という UI/プロンプト設計側で害を無効化する (推奨ではなく引用の文脈にする)。
# ---------------------------------------------------------------------------

# 高精度パターン: 「氏名+役職」+ 主要政党名。false positive がほぼ無い。
_POLITICAL_HIGH_PRECISION: list[re.Pattern[str]] = [
    re.compile(r"[一-鿿]{2,4}(議員|首相|総理|大臣|長官|知事|市長|町長|村長|区長)"),
    re.compile(
        r"(自民党|自由民主党|立憲民主党|立憲民主|公明党|国民民主党|国民民主|共産党|"
        r"日本共産党|維新の会|日本維新|社民党|社会民主党|れいわ新選組|れいわ|参政党|N国|無所属)"
    ),
]

# 敬称パターン: 「氏 / さん」。recall は上がるが「議員さん」等の誤検知源でもある。
# graceful degrade する agent (translator/relevance/concierge) では有効、
# 違反時に出力全体を破棄する agent (watcher) では include_honorific=False 推奨。
_POLITICAL_HONORIFIC: re.Pattern[str] = re.compile(r"[一-鿿]{2,4}(氏|さん)")

# 後方互換 / デバッグ用の全パターン一覧。
POLITICAL_LEAK_PATTERNS: list[re.Pattern[str]] = [
    *_POLITICAL_HIGH_PRECISION,
    _POLITICAL_HONORIFIC,
]

# 役職名そのもの (個人名の prefix でない = leak ではない)。timeline 実装と整合。
_ROLE_ONLY_PREFIXES: tuple[str, ...] = (
    "総理",
    "副総",
    "首相",
    "副首",
    "国務",
    "厚生",
    "農林",
    "経済",
    "総務",
    "文部",
    "外務",
    "防衛",
    "内閣",
    "副大",
    "副議",
    "副市",
    "副区",
    "副知",
)


def find_political_leak(text: str, *, include_honorific: bool = True) -> str | None:
    """text に政治家名 / 政党名 leak が含まれていれば最初の match を返す。

    「総理大臣」「副市長」等の *役職名のみ* で始まる match は除外
    (PROJECT.md §5 の「役職表現は可、個人の推奨・評価は不可」と整合)。

    Args:
        text: 検査対象。
        include_honorific: 「氏 / さん」パターンも見るか。違反時に出力全体を
            破棄する agent (watcher) では False を渡し、誤検知で分析全体が
            消えるのを防ぐ。既定 True (graceful degrade する agent 向け)。

    Returns:
        最初の match 文字列。違反なしなら None。
    """
    patterns = list(_POLITICAL_HIGH_PRECISION)
    if include_honorific:
        patterns.append(_POLITICAL_HONORIFIC)
    for pattern in patterns:
        for m in pattern.finditer(text):
            matched = m.group()
            if any(matched.startswith(role) for role in _ROLE_ONLY_PREFIXES):
                continue
            return matched
    return None
