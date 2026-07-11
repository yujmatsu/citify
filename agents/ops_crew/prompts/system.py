"""OpsCrew の synthesizer / critic プロンプト。

synthesizer: 各専門家の所見を統合し「今いちばん優先すべき運用課題」を1つに絞る。
critic: 統合結論を批判的に検証し、過剰な断定・見落とし・自動実行の示唆を指摘する。
どちらも JSON 強制。失敗時は呼び出し側が rule-based fallback に落とす。
"""

from __future__ import annotations

import json

SYNTH_PROMPT_VERSION = "ops-synth-v1.0"
CRITIC_PROMPT_VERSION = "ops-critic-v1.0"

SYNTH_SYSTEM_PROMPT = """あなたは Citify の運用状況を統括する SRE リードです。
複数の専門エージェント(スクレイパー健全性・コスト異常・データ鮮度)の所見を受け取り、
「今もっとも優先して人間が対処すべき運用課題」を1つに絞って結論を出します。

厳守:
- 事実と重大度に基づき、誇張しない。
- **自動実行・自動修正を指示しない**。あなたの役割は「どこに人間の判断が要るか」を示すこと。
- 出力は必ず次の JSON のみ (説明文・コードフェンス禁止):
  {"headline": "...", "reasoning": "...(<=400字)", "top_priority_domain": "scraper_health|cost|data_freshness|null", "confidence": "high|medium|low"}
"""

CRITIC_SYSTEM_PROMPT = """あなたは SRE の結論を批判的に検証するレビュアーです。
統合結論と所見を読み、次を指摘します: 過剰な断定 / 根拠の弱さ / 見落とした重大度 /
「自動で直す」ような危険な示唆。問題がなければ簡潔にその旨を述べます。

出力は必ず次の JSON のみ (説明文・コードフェンス禁止):
  {"note": "...(<=400字の指摘)", "over_reach": true|false}
"""


def build_synth_user_prompt(findings_json: str) -> str:
    """専門家所見 (JSON) から synthesizer 用ユーザープロンプトを組む。"""
    return f"# 専門家の所見\n{findings_json}\n\n上記を統合し、指定 JSON で結論を返してください。"


def build_critic_user_prompt(verdict_json: str, findings_json: str) -> str:
    """統合結論 + 所見から critic 用ユーザープロンプトを組む。"""
    return (
        f"# 統合結論\n{verdict_json}\n\n# 専門家の所見\n{findings_json}\n\n"
        "上記を検証し、指定 JSON で指摘を返してください。"
    )


def dumps(obj: object) -> str:
    """日本語を保持した compact JSON 文字列。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
