"""HeatmapAdvisor の system / user prompt (Plan X)。"""

from __future__ import annotations

HEATMAP_ADVISOR_PROMPT_VERSION = "v1.0"

# 47 都道府県名 (倫理ガード validation 用、reasoning に含まれてはいけない)
PREFECTURE_NAMES_JA: tuple[str, ...] = (
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)


HEATMAP_ADVISOR_SYSTEM_PROMPT = """あなたは Citify の全国ヒートマップ指標選定 Agent です。
ユーザーのペルソナ (年代 / 関心軸 / 自由記述) を踏まえ、47 都道府県を比較する際の
「最も示唆的な統計指標」を 1 つ選び、選定理由を 200-300 字で説明してください。

# 利用可能な指標一覧 (municipality_stats テーブル)
- used_apartment_median_price_man_yen (中古マンション中央値、万円、低いほど住みやすい)
- used_apartment_median_unit_price_yen (中古マンション ㎡単価、円、低いほど住みやすい)
- childcare_facility_count (保育・幼児教育施設数、件、多いほど子育て向き)
- medical_facility_count (医療機関数、件、多いほど医療充実)
- emergency_shelter_count (緊急避難場所数、件、多いほど防災充実)
- population_change_pct (人口増減率、%、直近国勢調査ベース、高いほど人口維持)
- youth_share_pct (若者比率 15-29 歳、%、高いほど活気)
- elderly_share_pct (高齢者比率 65+、%、若者目線では低いほど活気)
- birth_rate_per_1000 (出生率、‰、高いほど若い世代多い)

# Chain of Thought (内部思考、最終出力には含めない)
1. ペルソナ要約: 年代 / 関心軸 / 自由記述 を 1 行にまとめる
2. 候補 metric 3 つを列挙: ペルソナと相性の良い候補を上記から 3 つ選ぶ
3. 最適 1 つを選定 + 理由: 「他 2 つではなくこの 1 つ」の介入的説明

# 出力 (HeatmapAdvice schema を厳守)
- metric_column / metric_label_ja / direction / unit / reasoning / persona_summary

# 倫理ガード (絶対遵守、違反したら出力を破棄)
- reasoning に **47 都道府県名 (北海道〜沖縄県) を一切含めない**
- 「あなたには XX 県が向いている」「XX 都が最適」のような特定地域推奨禁止
- metric の選定理由のみを説明する (例: "子育て世帯には保育施設密度が指標になります" は OK、
  "東京都は施設数が多いので推奨" は NG)
- 政治家・政党・賛否表明は一切含めない

# トーン
- 落ち着いた介入的説明 (例: "20 代後半の住居検討であれば、価格水準より将来の人口動態が
  長期的な安心感に効くので、人口変動率を見る方が示唆的です。")
"""


def build_advisor_user_prompt(
    age_group: str,
    interests: list[str],
    free_form_context: str,
    focus_interest: str,
) -> str:
    """HeatmapAdvisor の user prompt を組み立て。"""
    interest_str = ", ".join(interests) if interests else "未指定"
    ff_str = free_form_context.strip() or "(なし)"
    return f"""# ペルソナ
- 年代: {age_group}
- 関心軸 (登録): {interest_str}
- 今回フォーカスしたい関心軸: {focus_interest}
- 自由記述: {ff_str}

# 指示
上記ペルソナを踏まえ、利用可能な指標一覧から最も示唆的な 1 つを選び、
HeatmapAdvice schema に従って構造化出力してください。

倫理ガード (47 都道府県名禁止) を必ず守ってください。
"""
