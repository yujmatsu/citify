"""voices_asp (VOICES/Web) スクレイパー本体。

httpx async + BeautifulSoup4 + lxml で Shift_JIS デコード + パース。
SPA でないので JS 実行不要、すべて HTML 内に server-render 済。

URL パターン (recon doc §4 から):
    GET {base}/g08v_viewh.asp                       → 本会議録 年度一覧
    GET {base}/g08v_viewh.asp?Sflg=11&FYY=N&TYY=N   → 本会議録 N 年分
    GET {base}/g08v_viewh.asp?Sflg=10               → 本会議録 全件 (定例会)
    GET {base}/g08v_views.asp                       → 委員会記録 年度一覧 (同構造想定)
    GET {base}/g08v_viewh.asp?Sflg=21&FYY=N&TYY=N   → 臨時会 N 年分
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import httpx

from .schema import MeetingSummary, MeetingType, Speech, YearEntry

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "Citify-Hackathon/0.1 (+https://github.com/yujmatsu/citify)"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_RATE_LIMIT_SEC = 1.0  # voices_asp の robots.txt は紳士運用、1 秒で十分
DEFAULT_ENCODING = "shift_jis"
MAX_RETRIES = 3

# 中央型 (gijiroku.com) のテンプレート
CENTRAL_BASE_URL_TEMPLATE = "https://{tenant_id}.gijiroku.com/voices"

# Sflg の意味 (recon doc §4 から)
SFLG_HONKAI_ALL = "10"  # 本会議録 全件
SFLG_HONKAI_YEAR = "11"  # 本会議録 N 年分 (FYY/TYY 必要)
SFLG_RINJI_ALL = "20"  # 臨時会 全件
SFLG_RINJI_YEAR = "21"  # 臨時会 N 年分

# 年度リストの候補 CSS セレクタ (推奨: ul.kaigi_view、フォールバック: 他テンプレ用)
YEAR_LIST_SELECTORS = [
    "ul.kaigi_view li a",  # recon doc §4 確認済
    "ul.year_list li a",
    "div.AreaGikaidoc a",
    "table.kaigi_view a",
    "a[href*='Sflg=']",  # 最後の砦: Sflg query を持つ全リンク
]

# 会議一覧の候補セレクタ
MEETING_LIST_SELECTORS = [
    "ul.kaigi_view li a",
    "ul.meeting_list li a",
    "table.kaigi_view tr a",
    "a[href*='g08v_']",  # g08v_minute_view.asp 等 individual meeting への link
]

# 発言ブロックの候補セレクタ
SPEECH_SELECTORS = [
    "div.speech",
    "div.speaker_speech",
    "table.gikaidoc tr",
    "div[class*='speech']",
    "p[class*='speech']",
]


def _parse_date_jp(text: str | None) -> date | None:
    """日本語 / ISO 日付を date に。"""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.match(r"令和(\d+)年(\d+)月(\d+)日", text)
    if m:
        return date(2018 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"平成(\d+)年(\d+)月(\d+)日", text)
    if m:
        return date(1988 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _extract_year_from_label(label: str) -> int | None:
    """'令和8年度' / '2025年度' / '2025' から西暦年を抽出。"""
    if not label:
        return None
    # 西暦 4 桁
    m = re.search(r"(20\d{2})", label)
    if m:
        return int(m.group(1))
    # 令和 N → 2018 + N
    m = re.search(r"令和\s*(\d+)", label)
    if m:
        return 2018 + int(m.group(1))
    # 平成 N → 1988 + N
    m = re.search(r"平成\s*(\d+)", label)
    if m:
        return 1988 + int(m.group(1))
    return None


def _make_soup(html: str) -> BeautifulSoup:
    """BeautifulSoup 構築 (lxml parser、遅延 import)。

    voices_asp は XHTML 1.0 で xml prolog を持つため、HTML parser で読むと
    XMLParsedAsHTMLWarning が出るが意図通り (HTML 風に select() 可)。warning は抑制。
    """
    import warnings

    from bs4 import BeautifulSoup

    try:
        from bs4 import XMLParsedAsHTMLWarning

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    except ImportError:
        pass

    return BeautifulSoup(html, "lxml")


class VoicesAspClient:
    """VOICES/Web スクレイパー (httpx async + BeautifulSoup)。

    Usage:
        async with VoicesAspClient(tenant_id="sapporo") as c:
            years = await c.fetch_year_list("honkai")
            meetings = await c.fetch_meetings_for_year(2025, "honkai")
            speeches = await c.fetch_speeches(meetings[0].detail_url)

    Args:
        tenant_id: テナント識別子 (sapporo, minato 等)
        base_url: scraper_base_url (例: https://sapporo.gijiroku.com/voices)。
                  None なら中央型テンプレートから生成
        encoding: HTML エンコーディング (default shift_jis)
        rate_limit_sec: 連続リクエスト間の最小間隔
    """

    def __init__(
        self,
        tenant_id: str,
        base_url: str | None = None,
        encoding: str = DEFAULT_ENCODING,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.base_url = (base_url or CENTRAL_BASE_URL_TEMPLATE.format(tenant_id=tenant_id)).rstrip(
            "/"
        ) + "/"
        self.encoding = encoding
        self.timeout_sec = timeout_sec
        self.rate_limit_sec = rate_limit_sec
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_sec,
            follow_redirects=True,
            transport=transport,
        )

    async def __aenter__(self) -> VoicesAspClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # 高レベル API
    # ------------------------------------------------------------------

    async def fetch_year_list(self, meeting_type: MeetingType = "honkai") -> list[YearEntry]:
        """年度一覧 (g08v_viewh.asp / g08v_views.asp トップから)。"""
        path = "g08v_viewh.asp" if meeting_type != "iinkai" else "g08v_views.asp"
        url = self.base_url + path
        html = await self._get_text(url)
        soup = _make_soup(html)

        # セレクタ順次試す
        for sel in YEAR_LIST_SELECTORS:
            anchors = soup.select(sel)
            if anchors:
                logger.info(
                    "voices_asp.year_list_selector_matched tenant=%s sel=%r count=%d",
                    self.tenant_id,
                    sel,
                    len(anchors),
                )
                return self._parse_year_anchors(anchors, base_url=url)

        logger.warning("voices_asp.no_year_list tenant=%s url=%s", self.tenant_id, url)
        return []

    async def fetch_meetings_for_year(
        self, year: int, meeting_type: MeetingType = "honkai"
    ) -> list[MeetingSummary]:
        """指定年度の会議一覧 (Sflg=11&FYY=N&TYY=N)。"""
        path = "g08v_viewh.asp" if meeting_type != "iinkai" else "g08v_views.asp"
        sflg = (
            SFLG_HONKAI_YEAR
            if meeting_type == "honkai"
            else (SFLG_RINJI_YEAR if meeting_type == "rinji" else SFLG_HONKAI_YEAR)
        )
        params = {"Sflg": sflg, "FYY": str(year), "TYY": str(year)}
        url = self.base_url + path
        html = await self._get_text(url, params=params)
        soup = _make_soup(html)

        # 会議リンク (href に g0 系の asp + Kid / minute_no 等の query があるもの)
        meetings: list[MeetingSummary] = []
        for sel in MEETING_LIST_SELECTORS:
            anchors = soup.select(sel)
            if not anchors:
                continue
            for i, a in enumerate(anchors):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if not href:
                    continue
                # 年度リストへの戻りリンクはスキップ
                if "Sflg=" in href and "FYY=" not in href:
                    continue
                council_id = self._extract_council_id(href) or f"row-{i}"
                detail_url = urljoin(url, href)
                meetings.append(
                    MeetingSummary(
                        tenant_id=self.tenant_id,
                        council_id=council_id,
                        meeting_date=_parse_date_jp(text),
                        name_of_meeting=text or f"meeting-{i}",
                        year=year,
                        meeting_type=meeting_type,
                        detail_url=detail_url,
                    )
                )
            if meetings:
                break

        logger.info(
            "voices_asp.fetch_meetings_done tenant=%s year=%d type=%s count=%d",
            self.tenant_id,
            year,
            meeting_type,
            len(meetings),
        )
        return meetings

    async def fetch_speeches(self, detail_url: str, max_speeches: int = 100) -> list[Speech]:
        """個別会議ページから発言を抽出。

        ⚠️ recon doc §9 残課題: 個別会議ページの DOM 構造未確認、複数セレクタで挑戦。
        失敗時は body 全文を 1 発言として fallback。
        """
        html = await self._get_text(detail_url)
        soup = _make_soup(html)

        for sel in SPEECH_SELECTORS:
            blocks = soup.select(sel)
            if not blocks:
                continue
            speeches = self._parse_speech_blocks(blocks, detail_url=detail_url)
            if speeches:
                logger.info(
                    "voices_asp.speech_selector_matched sel=%r n=%d",
                    sel,
                    len(speeches[:max_speeches]),
                )
                return speeches[:max_speeches]

        # フォールバック: body 全文を 1 発言として返す (parser 未対応構造の証跡保持)
        body = soup.find("body")
        body_text = body.get_text(separator="\n", strip=True) if body else ""
        logger.warning(
            "voices_asp.no_speech_selector url=%s, returning body fallback (%d chars)",
            detail_url,
            len(body_text),
        )
        return [
            Speech(
                tenant_id=self.tenant_id,
                council_id=self._extract_council_id(detail_url) or "(unknown)",
                name_of_meeting="(全文)",
                speech_order=0,
                speaker="(不明)",
                content_text=body_text[:5000],
                detail_url=detail_url,
            )
        ]

    async def inspect_page(self, path: str = "g08v_viewh.asp") -> dict:
        """指定パスを GET → DOM 構造ダンプ (デバッグ用)。"""
        url = self.base_url + path
        html = await self._get_text(url)
        soup = _make_soup(html)
        title = soup.title.string if soup.title and soup.title.string else ""

        candidates = []
        for sel in YEAR_LIST_SELECTORS + MEETING_LIST_SELECTORS + SPEECH_SELECTORS:
            try:
                elements = soup.select(sel)
                sample = elements[0].get_text(strip=True)[:120] if elements else ""
                candidates.append({"selector": sel, "count": len(elements), "sample_text": sample})
            except Exception as exc:  # noqa: BLE001
                candidates.append({"selector": sel, "error": str(exc)})

        return {
            "url": url,
            "title": title,
            "html_length": len(html),
            "table_count": len(soup.find_all("table")),
            "candidates": candidates,
        }

    # ------------------------------------------------------------------
    # 低レベル
    # ------------------------------------------------------------------

    async def _get_text(self, url: str, params: dict | None = None) -> str:
        """指定 URL を GET、Shift_JIS デコードして text 返す。retry 付き。"""
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                # 自動検出ではなく明示的に shift_jis を強制
                response.encoding = self.encoding
                text = response.text
                await asyncio.sleep(self.rate_limit_sec)
                return text
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "voices_asp.retry attempt=%d/%d url=%s exc=%s",
                    attempt,
                    MAX_RETRIES,
                    url,
                    exc,
                )
                if attempt == MAX_RETRIES:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError(
            f"voices_asp GET failed after {MAX_RETRIES} retries: {last_exc}"
        ) from last_exc

    def _parse_year_anchors(self, anchors: list, *, base_url: str) -> list[YearEntry]:
        """<a> タグから YearEntry リストを構築。"""
        entries: list[YearEntry] = []
        for a in anchors:
            href = a.get("href", "")
            label = a.get_text(strip=True)
            if not href and not label:
                continue
            # FYY=N から年度抽出を優先
            m = re.search(r"FYY=(\d+)", href)
            year: int | None = int(m.group(1)) if m else _extract_year_from_label(label)
            entries.append(
                YearEntry(
                    year=year,
                    label=label or f"year-{len(entries)}",
                    detail_url=urljoin(base_url, href) if href else base_url,
                )
            )
        return entries

    def _extract_council_id(self, href: str) -> str | None:
        """URL から会議の一意 ID を抽出 (Kid / minute_no / no / ID 等)。"""
        if not href:
            return None
        for key in ("Kid", "kid", "minute_no", "minuteNo", "Mno", "no", "id"):
            m = re.search(rf"[?&]{key}=([^&]+)", href)
            if m:
                return m.group(1)
        return None

    def _parse_speech_blocks(self, blocks: list, *, detail_url: str) -> list[Speech]:
        """発言ブロックの list から Speech list を構築。"""
        council_id = self._extract_council_id(detail_url) or "(extracted)"
        speeches: list[Speech] = []
        for i, block in enumerate(blocks):
            text = block.get_text(separator="\n", strip=True)
            if len(text) < 10:
                continue
            # 1 行目から speaker 抽出 (○氏名 + 役職)
            lines = text.split("\n", 1)
            first = lines[0]
            rest = lines[1] if len(lines) > 1 else ""
            m = re.match(r"^[○◯]?\s*([^\s(（]+)[\s(（]*([^)）]*)[)）]?\s*(.*)$", first)
            if m:
                speaker = m.group(1) or "(不明)"
                position = (m.group(2) or "").strip() or None
                body = (m.group(3) + ("\n" + rest if rest else "")).strip()
            else:
                speaker = "(不明)"
                position = None
                body = text
            speeches.append(
                Speech(
                    tenant_id=self.tenant_id,
                    council_id=council_id,
                    name_of_meeting="(unknown)",
                    speech_order=i,
                    speaker=speaker,
                    speaker_position=position,
                    content_text=body,
                    detail_url=detail_url,
                )
            )
        return speeches
