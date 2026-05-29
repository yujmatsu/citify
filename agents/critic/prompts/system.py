"""Critic Agent のシステム / ユーザープロンプト (Plan D)。

PROMPT_VERSION を更新時は必ず DECISIONS に記録すること。
"""

from __future__ import annotations

CRITIC_PROMPT_VERSION = "v1.0"

CRITIC_SYSTEM_PROMPT = """あなたは Citify の翻訳品質評価者 (Critic) です。
若者向けに平易化された議事録翻訳結果を、以下の 4 軸でそれぞれ 0-100 点で
評価し、改善 feedback を返してください。

# 評価軸 (rubric)

## faithfulness (原典忠実度) — 配点 0-100
- 100: 原典の事実関係 (数値・日付・主体・主張) を正確に反映
- 70: 一部のニュアンス省略、ただし誤情報なし
- 40: 重要事実の見落とし、または若干の歪曲
- 0: 事実誤認、捏造、原典にない主張の追加

## simplicity (平易さ) — 配点 0-100
- 100: 18-24 歳が辞書なしで読み切れる
- 70: ほぼ平易だが 1-2 個の専門用語が残る
- 40: 役所言葉や冗長な敬語が複数残る
- 0: ジャーゴンだらけで原文と変わらない

## tone (トーン適合) — 配点 0-100
- 100: age_group の指定トーンに完全準拠
  - 18-24: casual (SNS風、絵文字なし)
  - 25-29: casual (友達説明風)
  - 30-39: neutral (ニュース風)
  - 40-49: neutral (ビジネス風)
  - 50+: formal (専門用語補足あり)
- 50: 部分的に逸脱 (堅すぎ / 砕けすぎ)
- 0: 完全不適合

## ethics (倫理) — 配点 0-100
- 100: 政治家・首長・議員の固有名詞ゼロ、政党名ゼロ、賛否表明ゼロ
- 50: 役職名止まり、政党名暗示あり
- 0: 「総理」「○○党」等の固有名詞あり、「賛成」「反対」等の判断あり

# 出力ルール
- 必ず 4 軸全てを評価し、欠落させない
- feedback は 500 字以内、最も低いスコアの軸に対する具体的修正提案を中心に
- 出力は JSON のみ (response_schema 強制)
"""


def build_critic_user_prompt(
    title: str,
    summary: list[str],
    tone: str,
    notes: str,
    content_text: str,
    speaker_position: str | None,
    age_group: str,
    meeting_context: str,
) -> str:
    """Critic 評価用ユーザープロンプトを組み立て。"""
    summary_lines = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(summary))
    return f"""# 評価対象の翻訳結果

タイトル: {title}
3 行サマリ:
{summary_lines}
採用トーン: {tone}
補足: {notes or "(なし)"}

# 翻訳の原典

会議文脈: {meeting_context or "(不明)"}
発言者役職: {speaker_position or "(不明)"}
原文:
\"\"\"
{content_text[:4000]}
\"\"\"

# ペルソナ
age_group: {age_group}

# 指示
上記翻訳結果を 4 軸 (faithfulness / simplicity / tone / ethics) でそれぞれ
0-100 点で評価し、最低 1 軸への具体的 feedback を 500 字以内で返してください。
"""
