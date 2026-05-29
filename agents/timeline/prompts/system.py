"""Timeline Agent の system / user prompt (Plan N)。"""

from __future__ import annotations

TIMELINE_PROMPT_VERSION = "v1.0"

TIMELINE_SYSTEM_PROMPT = """あなたは Citify の議論タイムライン編集者 (Timeline Editor) です。
与えられた議題候補 (時系列順) を分析し、若者向けに 5-10 個の重要イベントで議論変遷を物語化してください。

# Chain of Thought (内部思考、最終出力に含めない)
1. 候補を時系列でグルーピング (重複・類似議題を圧縮)
2. 各グループから「最も重要な発言 / 転換点」を 5-10 個抽出
3. 各イベントに 40 字以内のキャッチーな headline + 80 字以内の detail を付与
4. 全体ナラティブ (overall_summary 200-240 字) で「議論はどこから始まり、どう発展し、今どこに居るか」を物語化

# 重要: theme_interest 軸 (e.g. "住居") に絞った物語です
- candidates の matched_interests は複数軸を持つ場合あり
- theme_interest 軸に関連する話題のみを抽出し、他軸の話題は無視してください

# 出力 (TimelineNarrative schema 厳守)
- theme_label / period_start / period_end / overall_summary / events[]
- 各 event の source_speech_id は **必ず candidate の speech_id から選ぶ** (捏造禁止)
- events は 5-10 件 (3 件未満なら fallback されるため最低 5 件目指す)

# 倫理ガード (絶対遵守、違反したら出力を破棄)
- **政治家・首長・議員の固有名詞は絶対に使わない** (speaker_position まで使用可)
- **政党名は禁止** (自民党・立憲民主党・公明党・国民民主党・共産党・維新の会・社民党・れいわ・参政党 等)
- **賛否表明・投票推奨は禁止**
- 例 NG: "石破総理が提案" / "立憲民主党が反対" / "賛成すべき"
- 例 OK: "総理大臣が提案" / "野党側が反対" / "議論が継続"
- 違反したら出力全体が破棄されます。検証は後段で regex 機械チェックされます。

# トーン
- 若者向け、ニュース見出し風、平易な日本語
- 数値・固有制度名は積極的に活用 (例: "保育園待機児童 500 人超で施策強化")
- ジャーゴン・敬語は避ける
"""


def build_timeline_user_prompt(
    theme_interest: str,
    municipality_code: str | None,
    period_start_iso: str,
    period_end_iso: str,
    candidates_text: str,
) -> str:
    """user prompt を組み立て。candidates は呼び元で整形済の文字列を渡す。"""
    muni_str = municipality_code if municipality_code else "全国 (multiple municipalities)"
    return f"""# フォーカス
- theme_interest: {theme_interest}
- municipality_scope: {muni_str}
- period: {period_start_iso} 〜 {period_end_iso}

# 候補 speeches (時系列順、最大 30 件)
{candidates_text}

# 指示
上記候補から「{theme_interest}」軸の議論変遷を 5-10 イベントで物語化してください。
TimelineNarrative schema に従って構造化出力してください。
"""


def format_candidate_line(
    idx: int,
    speech_id: str,
    meeting_date_iso: str,
    municipality_name: str,
    title: str,
    summary_first_line: str,
    speaker_position: str | None,
) -> str:
    """1 candidate を LLM context 用の 1 ブロックに整形 (token 節約)。"""
    role = speaker_position or "発言者不明"
    return (
        f"[{idx}] speech_id={speech_id}\n"
        f"  date={meeting_date_iso} / 自治体={municipality_name} / 発言者役職={role}\n"
        f"  title: {title}\n"
        f"  summary: {summary_first_line}\n"
    )
