"""プレスリリース RSS の Pydantic スキーマ。

BigQuery 投入時は kokkai_speeches と同様の共通設計 (id / source / municipality_code
/ content_text / fetched_at) で統一可能なように設計。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

SOURCE_NAME = "press_rss"


class PressItem(BaseModel):
    """RSS の 1 件 (item / entry) を表現。"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(
        description="一意 ID。RSS guid > link > 自動生成 hash の順で fallback",
    )
    municipality_code: str = Field(
        description="自治体コード 5 桁 ('00000' = 国会には使わない、自治体のみ)",
    )
    title: str = Field(description="記事タイトル")
    link: str = Field(description="プレスリリース詳細ページ URL")
    description: str | None = Field(default=None, description="RSS description (HTML/text)")
    pub_date: datetime | None = Field(default=None, description="公開日 (timezone-aware)")
    category: str | None = Field(default=None, description="カテゴリ (お知らせ/イベント 等)")
    source_url: str = Field(description="取得元 RSS feed URL")
    fetched_at: datetime = Field(description="取得時刻 (UTC)")
