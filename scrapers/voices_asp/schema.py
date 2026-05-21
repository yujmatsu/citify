"""voices_asp スクレイパーの Pydantic スキーマ。

kaigiroku_net とほぼ同形 (BigQuery 投入時に統一スキーマで扱えるため)。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# voices_asp が扱う会議種別 (Sflg パラメタで切り替え)
MeetingType = Literal["honkai", "iinkai", "rinji"]
# honkai = 本会議 (g08v_viewh.asp), iinkai = 委員会 (g08v_views.asp), rinji = 臨時会 (Sflg=20/21)


class YearEntry(BaseModel):
    """年度リスト 1 件 (g08v_viewh.asp トップから取得)。"""

    model_config = ConfigDict(extra="allow")

    year: int | None = Field(default=None, description="年度 (西暦)")
    label: str = Field(description="表示ラベル (例: '令和8年度', '2025')")
    detail_url: str = Field(description="その年度の会議一覧 URL")


class MeetingSummary(BaseModel):
    """年度内の会議録 1 件。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(description="自治体テナント (sapporo, minato 等)")
    council_id: str = Field(description="会議の一意 ID (URL から抽出)")
    meeting_date: date | None = Field(default=None)
    name_of_meeting: str = Field(description="第N回定例会・第N委員会 等")
    year: int | None = Field(default=None)
    meeting_type: MeetingType = Field(default="honkai")
    detail_url: str = Field(description="会議録詳細ページ URL")


class Speech(BaseModel):
    """1 議事録内の 1 発言。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str
    council_id: str
    meeting_date: date | None = None
    name_of_meeting: str
    speech_order: int = Field(ge=0)
    speaker: str
    speaker_position: str | None = None
    content_text: str
    detail_url: str
