"""kaigiroku.net DiscussNet SPA を Playwright async で巡回するクライアント。

⚠️ 設計上の前提: SPA の DOM 構造は非公開で recon ベース。実 site で適合しない
   場合に備え、複数のフォールバックセレクタを試す + inspect サブコマンドで
   構造ダンプ可能にしている。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from .schema import MeetingSummary, Speech

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

USER_AGENT = "CitifyBot/0.1 (+https://github.com/yujmatsu/citify)"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_RATE_LIMIT_SEC = 5.0  # 自治体サイトへの礼儀

CENTRAL_BASE_URL_TEMPLATE = "https://ssp.kaigiroku.net/tenant/{tenant_id}/"

# 会議一覧 SPA の候補セレクタ (実 DOM 確認後に絞る)
MEETING_LIST_SELECTORS = [
    "#council_list tr",
    "table.meeting-list tr",
    "tbody.councilList tr",
    ".result-list tr",
    "table tbody tr",  # 最後の砦
]

# 発言 SPA の候補セレクタ
SPEECH_LIST_SELECTORS = [
    ".speech-item",
    "div.speech",
    "li.speech",
    "div[class*='speech']",
]


def _parse_date_jp(text: str | None) -> date | None:
    """日本語日付 (例: '令和8年4月15日', '2026/04/15', '2026-04-15') を date に。"""
    if not text:
        return None
    text = text.strip()
    # ISO 形式
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # 令和 (R) を西暦に: 令和 N 年 = 2018 + N
    import re

    m = re.match(r"令和(\d+)年(\d+)月(\d+)日", text)
    if m:
        y = 2018 + int(m.group(1))
        return date(y, int(m.group(2)), int(m.group(3)))
    return None


class KaigirokuNetClient:
    """kaigiroku.net DiscussNet SPA の async スクレイパー (Playwright ベース)。

    Usage:
        async with KaigirokuNetClient(tenant_id="arakawa") as client:
            meetings = await client.list_meetings()
            speeches = await client.fetch_speeches(meetings[0].detail_url)

    Args:
        tenant_id: テナント ID (例: arakawa, yokohama)
        base_url: 白ラベル型用の上書き URL (None なら中央型 ssp.kaigiroku.net)
        headless: True で headless Chromium、False で目視デバッグ
        timeout_ms: ページ遷移 / セレクタ待機タイムアウト
        rate_limit_sec: 連続リクエスト間の待機秒数 (倫理)
    """

    def __init__(
        self,
        tenant_id: str,
        base_url: str | None = None,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    ) -> None:
        self.tenant_id = tenant_id
        self.base_url = (base_url or CENTRAL_BASE_URL_TEMPLATE.format(tenant_id=tenant_id)).rstrip(
            "/"
        ) + "/"
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.rate_limit_sec = rate_limit_sec
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> KaigirokuNetClient:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        logger.info(
            "kaigiroku.session_start tenant=%s base=%s headless=%s",
            self.tenant_id,
            self.base_url,
            self.headless,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        logger.info("kaigiroku.session_end tenant=%s", self.tenant_id)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def inspect_page(self, path: str = "MinuteBrowse.html") -> dict:
        """指定パスを開いて DOM 構造をダンプ (デバッグ + セレクタ決定用)。

        Returns:
            {url, title, table_count, candidate_rows: [{selector, count, sample_text}, ...]}
        """
        url = self.base_url + path
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            page_title = await page.title()

            # 候補セレクタ別の count を確認
            candidate_rows = []
            for sel in MEETING_LIST_SELECTORS:
                try:
                    count = await page.locator(sel).count()
                    sample = ""
                    if count > 0:
                        sample = (await page.locator(sel).first.inner_text())[:120]
                    candidate_rows.append({"selector": sel, "count": count, "sample_text": sample})
                except Exception as exc:  # noqa: BLE001
                    candidate_rows.append({"selector": sel, "error": str(exc)})

            table_count = await page.locator("table").count()
            body_html_len = len(await page.content())

            return {
                "url": url,
                "title": page_title,
                "table_count": table_count,
                "body_html_length": body_html_len,
                "candidate_rows": candidate_rows,
            }
        finally:
            await page.close()

    async def list_meetings(
        self, path: str = "MinuteBrowse.html", max_items: int = 50
    ) -> list[MeetingSummary]:
        """会議一覧 SPA をレンダリング → 会議メタを抽出。

        DOM が想定外の場合は空 list を返し、warning ログを残す。
        """
        url = self.base_url + path
        page = await self._new_page()
        try:
            logger.info("kaigiroku.list_meetings url=%s", url)
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)

            # セレクタを順に試す
            rows_selector: str | None = None
            for sel in MEETING_LIST_SELECTORS:
                try:
                    count = await page.locator(sel).count()
                    if count > 0:
                        rows_selector = sel
                        logger.info("kaigiroku.selector_matched selector=%r count=%d", sel, count)
                        break
                except Exception:  # noqa: BLE001
                    continue

            if rows_selector is None:
                logger.warning(
                    "kaigiroku.no_meeting_list_selector_matched tenant=%s url=%s",
                    self.tenant_id,
                    url,
                )
                return []

            # 各 row から情報抽出 (heuristic、複数列を試す)
            raw_meetings = await page.evaluate(
                """(selector) => {
                    const rows = Array.from(document.querySelectorAll(selector));
                    return rows.slice(0, 100).map(row => {
                        const cells = row.querySelectorAll('td');
                        const link = row.querySelector('a[href]');
                        return {
                            text_all: row.innerText?.trim() || '',
                            cell_texts: Array.from(cells).map(c => c.innerText?.trim() || ''),
                            link_href: link?.href || '',
                            link_text: link?.innerText?.trim() || '',
                        };
                    });
                }""",
                rows_selector,
            )

            import re

            meetings: list[MeetingSummary] = []
            for i, raw in enumerate(raw_meetings):
                if i >= max_items:
                    break

                # MinuteBrowse は階層ビュー: 委員会名のみ / 日付のみ / 個別会議など色々混在
                # 抽出戦略: cell_texts または link_text / text_all を組み合わせて name + date を推定
                cells = raw["cell_texts"]
                link_href = raw["link_href"]
                link_text = raw["link_text"]
                text_all = raw["text_all"]

                # 日付抽出: cell の中で最初に日付パターンに match するもの
                meeting_date = None
                for cell in cells + [text_all]:
                    meeting_date = _parse_date_jp(cell)
                    if meeting_date:
                        break
                    # cell から日付っぽい部分を切り出して再試行
                    m = re.search(r"令和\d+年\d+月\d+日|\d{4}[-/]\d{1,2}[-/]\d{1,2}", cell or "")
                    if m:
                        meeting_date = _parse_date_jp(m.group(0))
                        if meeting_date:
                            break

                # 会議名: cell の中で「委員会」「本会議」を含むもの優先、なければ link_text or 最初の非空 cell
                name_of_meeting = ""
                for cell in cells:
                    if any(kw in cell for kw in ("委員会", "本会議", "定例会", "公聴会", "審議会")):
                        name_of_meeting = cell.strip()
                        break
                if not name_of_meeting:
                    name_of_meeting = link_text or next((c for c in cells if c.strip()), "")
                if not name_of_meeting:
                    continue  # 完全な空行スキップ

                # council_id: URL の query / path から抽出
                council_id = f"row-{i}"
                if link_href:
                    m = re.search(
                        r"[?&](?:no|councilId|cid|id|kaigiId|minuteNo)=([^&]+)", link_href
                    )
                    if m:
                        council_id = m.group(1)
                    else:
                        # path 末尾の数字
                        m = re.search(r"/(\d+)(?:\.html?|/?$)", link_href)
                        if m:
                            council_id = m.group(1)

                # detail_url: link があればそれ、なければ親 url
                detail_url = link_href or url

                meetings.append(
                    MeetingSummary(
                        tenant_id=self.tenant_id,
                        council_id=council_id,
                        meeting_date=meeting_date,
                        name_of_meeting=name_of_meeting,
                        title=link_text or None,
                        detail_url=detail_url,
                    )
                )

            logger.info("kaigiroku.list_meetings_done n=%d", len(meetings))
            return meetings
        finally:
            await page.close()

    async def fetch_speeches(self, detail_url: str, max_speeches: int = 100) -> list[Speech]:
        """1 議事録の発言を抽出 (SPA navigation + scroll/click 込み)。"""
        page = await self._new_page()
        try:
            logger.info("kaigiroku.fetch_speeches url=%s", detail_url)
            await page.goto(detail_url, wait_until="networkidle", timeout=self.timeout_ms)

            # 発言セレクタを試す
            speech_selector: str | None = None
            for sel in SPEECH_LIST_SELECTORS:
                try:
                    count = await page.locator(sel).count()
                    if count > 0:
                        speech_selector = sel
                        logger.info("kaigiroku.speech_selector=%r count=%d", sel, count)
                        break
                except Exception:  # noqa: BLE001
                    continue

            if speech_selector is None:
                logger.warning("kaigiroku.no_speech_selector url=%s", detail_url)
                # フォールバック: body 全文をひとつの speech として扱う
                body_text = await page.locator("body").inner_text()
                return [
                    Speech(
                        tenant_id=self.tenant_id,
                        council_id="(unknown)",
                        name_of_meeting="(全文)",
                        speech_order=0,
                        speaker="(不明)",
                        content_text=body_text[:5000],
                        detail_url=detail_url,
                    )
                ]

            raw_speeches = await page.evaluate(
                """(selector) => {
                    const els = Array.from(document.querySelectorAll(selector));
                    return els.map(el => ({
                        text: el.innerText?.trim() || '',
                    }));
                }""",
                speech_selector,
            )

            speeches: list[Speech] = []
            for i, raw in enumerate(raw_speeches):
                if i >= max_speeches:
                    break
                text = raw["text"]
                if len(text) < 10:
                    continue
                # heuristic: 1 行目から speaker 抽出 (○氏名 + 役職)
                lines = text.split("\n", 1)
                first_line = lines[0]
                rest = lines[1] if len(lines) > 1 else ""
                import re

                m = re.match(r"^[○◯]?([^\s（(]+)\s*[（(]?([^)）]*)?[)）]?\s*(.*)$", first_line)
                if m:
                    speaker = m.group(1)
                    position = (m.group(2) or "").strip() or None
                    body = (m.group(3) + rest).strip() if rest else (m.group(3) or "")
                else:
                    speaker = "(不明)"
                    position = None
                    body = text

                speeches.append(
                    Speech(
                        tenant_id=self.tenant_id,
                        council_id="(extracted)",
                        name_of_meeting="(unknown)",
                        speech_order=i,
                        speaker=speaker,
                        speaker_position=position,
                        content_text=body,
                        detail_url=detail_url,
                    )
                )

            logger.info("kaigiroku.fetch_speeches_done n=%d", len(speeches))
            return speeches
        finally:
            await page.close()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("KaigirokuNetClient must be used as async context manager")
        return await self._context.new_page()
