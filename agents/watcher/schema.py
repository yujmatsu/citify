"""マイ街エージェント (Watcher) の入出力スキーマ (TASK-WATCHER Slice 1)。

自律型 Civic Watch Agent: ユーザーのウォッチ街(住む街 + 気になる街)の新着から、
本人に意味があるものを *エージェントが自分で判断・調査して* 見つける。
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from agents.relevance.schema import AgeGroup, Interest

Significance = Literal["high", "medium", "low"]


class WatchInput(BaseModel):
    """1 ユーザー分のウォッチ・コンテキスト (エージェント実行の入力)。"""

    user_id: str
    age_group: AgeGroup
    interests: list[Interest] = Field(default_factory=list)
    home_municipality_code: str = Field(description="住む街 (5 桁)")
    watched_codes: list[str] = Field(
        default_factory=list, description="気になる街 (home 含め上限 5)"
    )

    MAX_TOWNS: ClassVar[int] = 5

    def all_codes(self) -> list[str]:
        """home + watched を重複なしで返す (home 先頭、上限 MAX_TOWNS で truncate)。

        上限超過は ValidationError で止めず先頭 N 件に truncate (graceful 思想)。
        """
        seen: list[str] = []
        for c in [self.home_municipality_code, *self.watched_codes]:
            if c and c not in seen:
                seen.append(c)
        return seen[: self.MAX_TOWNS]


class Discovery(BaseModel):
    """エージェントが「あなたに意味がある」と判断して surface する 1 件の発見。"""

    municipality_code: str
    title: str = Field(max_length=60, description="若者向けの短いタイトル")
    summary: list[str] = Field(default_factory=list, description="3 行以内のサマリ")
    why_surfaced: str = Field(
        max_length=200,
        description="なぜ *あなたに* surface したかの理由 (関心/人生段階/街の文脈)。差別化の核",
    )
    significance: Significance = Field(description="エージェントの重要度自己評価")
    source_speech_ids: list[str] = Field(
        default_factory=list, description="根拠となった議題 speech_id (引用必須)"
    )
    contains_political_judgment: bool = Field(
        default=False, description="倫理チェック: 賛否表明/政党推奨を含むか"
    )


class ToolCall(BaseModel):
    """エージェントが自律的に実行したツール呼び出し 1 回の記録 (①の自律証跡)。"""

    tool: str
    args: dict = Field(default_factory=dict)


class AgentRunLog(BaseModel):
    """1 回の自律実行ログ (agent_runs 相当、透明性 + コスト監視)。"""

    run_id: str = Field(default="", description="一意な実行 ID (logs↔discoveries の join 用)")
    user_id: str
    towns_checked: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(
        default_factory=list, description="LLM が自分で選んで呼んだツール列 = 自律性の証跡"
    )
    n_discoveries: int = 0
    token_cost: int | None = Field(
        default=None, description="最終 event の usage (取れなければ None)"
    )
    status: Literal["ok", "empty", "error", "max_iterations"] = "ok"
    note: str = ""


class WatcherResult(BaseModel):
    """エージェント 1 実行の最終結果。"""

    discoveries: list[Discovery] = Field(default_factory=list)
    run_log: AgentRunLog
