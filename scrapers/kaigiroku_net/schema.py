"""kaigiroku.net DiscussNet スクレイパーの Pydantic スキーマ。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class MeetingSummary(BaseModel):
    """会議録一覧から取得した会議メタ (1 議事録 = 1 件)。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(description="自治体テナント ID (例: arakawa, yokohama)")
    council_id: str = Field(description="会議の一意 ID (URL から抽出)")
    meeting_date: date | None = Field(default=None, description="開催日")
    name_of_meeting: str = Field(description="会議名 (本会議 / 委員会名 等)")
    title: str | None = Field(default=None, description="会議のタイトル / 議題")
    detail_url: str = Field(description="会議録詳細ページ URL")


class Speech(BaseModel):
    """1 議事録内の 1 発言。"""

    model_config = ConfigDict(extra="allow")

    tenant_id: str
    council_id: str
    meeting_date: date | None = None
    name_of_meeting: str
    speech_order: int = Field(ge=0, description="同一会議内の発言順 (0-based)")
    speaker: str = Field(description="発言者名")
    speaker_position: str | None = Field(default=None, description="役職 (議員/部長 等)")
    content_text: str = Field(description="発言本文")
    detail_url: str = Field(description="親会議の URL (anchor で発言位置指定可)")
