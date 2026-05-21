"""kaigiroku.net DiscussNet スクレイパーの Pydantic スキーマ。

ツリー構造:
- L1: MeetingSummary  = 定例会・臨時会の council (data-council_id)
- L2: MeetingSchedule = council 配下の個別会議日 (schedule_id)
- L3: Speech          = 会議日内の 1 発言
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class MeetingSummary(BaseModel):
    """L1: 定例会 / 臨時会 のメタ (例: 令和7年2月定例会, council_id=177)。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(description="自治体テナント ID (例: arakawa, prefokayama)")
    council_id: str = Field(description="council 一意 ID (data-council_id 由来)")
    meeting_date: date | None = Field(
        default=None, description="開催日 (council は会期があるため通常 None)"
    )
    name_of_meeting: str = Field(description="会議名 (定例会 / 臨時会 等の総称)")
    title: str | None = Field(default=None, description="link-council テキスト (詳細名)")
    detail_url: str = Field(description="MinuteSchedule.html?council_id=N の L2 URL")


class MeetingSchedule(BaseModel):
    """L2: council 配下の個別会議日 (例: P.1 02月21日−01号, schedule_id=1)。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str
    council_id: str
    schedule_id: str = Field(description="会議日 ID (URL の schedule_id 由来)")
    page_label: str | None = Field(default=None, description="冒頭ページ表記 (例: 'P.1')")
    title: str = Field(description="会議日タイトル (例: '02月21日－01号')")
    meeting_date: date | None = Field(default=None, description="会議日付")
    detail_url: str = Field(description="MinuteView.html?council_id=N&schedule_id=M の L3 URL")


class Speech(BaseModel):
    """L3: 1 議事録内の 1 発言ブロック。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str
    council_id: str
    schedule_id: str | None = Field(default=None, description="L2 schedule_id (リンク用)")
    meeting_date: date | None = None
    name_of_meeting: str
    speech_order: int = Field(ge=0, description="同一会議内の発言順 (0-based)")
    speech_type: str | None = Field(
        default=None, description="冒頭マーク: ○ (発言) / △ (議題) / ◎ (答弁) 等"
    )
    speaker: str = Field(description="発言者名 (君 / さん 等の敬称除去)")
    speaker_position: str | None = Field(default=None, description="役職 (議長 / 知事 / 部長 等)")
    content_text: str = Field(description="発言本文")
    detail_url: str = Field(description="親会議の URL")
