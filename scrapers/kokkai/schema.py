"""国会会議録 API のレスポンス Pydantic スキーマ。

公式仕様 (https://kokkai.ndl.go.jp/api.html) の speech エンドポイント JSON を
モデル化。フィールド名は camelCase (API) ↔ snake_case (Python) を alias で吸収。

API が将来フィールドを追加しても落ちないよう `extra="allow"` で受ける。
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SpeechRecord(BaseModel):
    """国会会議録の発言レコード (speech 単位)。

    API の `speechRecord` 配列の 1 要素に対応。
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    speech_id: str = Field(alias="speechID", description="発言の一意 ID")
    issue_id: str = Field(alias="issueID", description="会議録の一意 ID")
    image_kind: str | None = Field(default=None, alias="imageKind")
    session: int = Field(description="国会回次 (例: 215)")
    name_of_house: str = Field(alias="nameOfHouse", description="衆議院 / 参議院")
    name_of_meeting: str = Field(alias="nameOfMeeting", description="本会議 / 予算委員会 等")
    issue: str = Field(description="会議号数 (例: 第16号)")
    meeting_date: date = Field(alias="date", description="開催日 (YYYY-MM-DD)")
    speech_order: int = Field(alias="speechOrder", description="同一会議内の発言順序")
    speaker: str = Field(description="発言者名")
    speaker_yomi: str | None = Field(default=None, alias="speakerYomi")
    speaker_group: str | None = Field(
        default=None, alias="speakerGroup", description="所属政党 (例: 自由民主党)"
    )
    speaker_position: str | None = Field(
        default=None, alias="speakerPosition", description="役職 (例: 内閣総理大臣)"
    )
    speech: str = Field(description="発言本文。倫理制約により全文転載禁止、内部 RAG のみ")
    start_page: int | None = Field(
        default=None,
        alias="startPage",
        description="開始ページ番号。実 API は int (0/1/2...)、spec doc の str は古い情報",
    )
    speech_url: str = Field(alias="speechURL", description="発言原典 URL")
    meeting_url: str = Field(alias="meetingURL", description="会議録原典 URL")


class SearchResponse(BaseModel):
    """`/api/speech` エンドポイントのトップレベルレスポンス。"""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    number_of_records: int = Field(
        alias="numberOfRecords", description="検索条件にマッチする総件数"
    )
    number_of_return: int = Field(alias="numberOfReturn", description="このレスポンスで返した件数")
    start_record: int = Field(alias="startRecord", description="このページの開始位置 (1-based)")
    next_record_position: int | None = Field(
        default=None,
        alias="nextRecordPosition",
        description="次ページの開始位置。最終ページの場合 None または欠落",
    )
    speech_record: list[SpeechRecord] = Field(
        default_factory=list, alias="speechRecord", description="発言レコードのリスト"
    )
