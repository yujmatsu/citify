"""kaigiroku.net DiscussNet SPA を Playwright async で巡回するクライアント。

ツリー構造 (recon: docs/scrapers/kaigiroku_net_recon.md):
- L1: MinuteBrowse.html          → 定例会・臨時会一覧 (#council_list)
- L2: MinuteSchedule.html?cid=N  → 会議日一覧 (P.1, P.13, ...)
- L3: MinuteView.html?cid=N&sid=M → 発言ブロック (.detail-genuine)

robots.txt: `/dnp/` (API) は Disallow、`/tenant/*.html` は Allow。
Playwright は実ブラウザ振る舞いなので倫理的にクリア (recon §3 参照)。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from .schema import MeetingSchedule, MeetingSummary, Speech

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

USER_AGENT = "CitifyBot/0.1 (+https://github.com/yujmatsu/citify)"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_RATE_LIMIT_SEC = 5.0  # 自治体サイトへの礼儀 (recon §5.3)

CENTRAL_BASE_URL_TEMPLATE = "https://ssp.kaigiroku.net/tenant/{tenant_id}/"

# 会議一覧 SPA の候補セレクタ
# 注: tenant により tbody の id 命名が異なる:
#   - prefokayama: "#council_list" (underscore)
#   - yokohama:    "#council-list" (hyphen) + table#tbl-council
COUNCIL_LIST_SELECTORS = [
    "#council_list tr",
    "#council-list tr",
    "#tbl-council tbody tr",
    "tbody.councilList tr",  # 旧テンプレ互換
    "table.meeting-list tr",
]

# 個別会議日 (L2) のリンク
SCHEDULE_LINK_SELECTORS = [
    "a.link-minute-view",
    ".link-minute-view",
    "a[class*='minute-view']",
]

# 発言ブロック (L3) - .detail-genuine が full text 版、.detail-ellipsis は collapsed
SPEECH_BLOCK_SELECTORS = [
    ".detail-speech-list .detail-genuine",
    ".detail-speech-list > div",  # フォールバック
    ".speech-item",
    "div[class*='detail-speech']",
]

# 発言者行のパース: "○議長（久徳大輔君）　　皆さん..."
#   group(1): 発言種別マーク (○ / ◯ / △ / ◎)
#   group(2): 役職 (例: "議長")
#   group(3): 括弧内の名前 (例: "久徳大輔君") - 括弧が無ければ None
#   group(4): 本文 (1行目残部、改行以降は別途連結)
SPEAKER_LINE_RE = re.compile(r"^([○◯△◎])\s*([^\s（(]+)(?:\s*[（(]\s*([^）)]*)\s*[）)])?\s*(.*)$")


def _parse_date_jp(text: str | None) -> date | None:
    """日本語日付 (例: '令和8年4月15日', '2026/04/15') を date に。"""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.match(r"令和(\d+)年(\d+)月(\d+)日", text)
    if m:
        y = 2018 + int(m.group(1))
        return date(y, int(m.group(2)), int(m.group(3)))
    m = re.match(r"平成(\d+)年(\d+)月(\d+)日", text)
    if m:
        y = 1988 + int(m.group(1))
        return date(y, int(m.group(2)), int(m.group(3)))
    return None


def _parse_schedule_title_to_date(title: str, base_year: int | None = None) -> date | None:
    """L2 schedule タイトル (例: '02月21日－01号') を date に変換。

    base_year が指定されていればそれを使う、なければ None (年情報なし)。
    """
    m = re.search(r"(\d{1,2})月\s*(\d{1,2})日", title or "")
    if m and base_year:
        try:
            return date(base_year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _extract_view_year_from_council_name(name: str) -> int | None:
    """council 名 (例: '令和　７年　２月定例会') から年を抽出。"""
    m = re.search(r"令和\s*([０-９0-9]+)\s*年", name)
    if not m:
        return None
    # 全角数字→半角
    digits = m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    try:
        return 2018 + int(digits)
    except ValueError:
        return None


def _parse_speech_block(text: str) -> tuple[str | None, str, str | None, str]:
    """発言ブロック text から (speech_type, speaker, position, body) を抽出。

    Example:
        "○議長（久徳大輔君）　　皆さん、おはようございます。\n..."
        → ("○", "久徳大輔", "議長", "皆さん、おはようございます。\n...")
    """
    if not text:
        return None, "(不明)", None, ""
    lines = text.split("\n", 1)
    first = lines[0].strip()
    rest = lines[1] if len(lines) > 1 else ""

    m = SPEAKER_LINE_RE.match(first)
    if not m:
        return None, "(不明)", None, text.strip()

    speech_type = m.group(1)
    position_raw = (m.group(2) or "").strip()  # 例: "議長"
    speaker_raw = (m.group(3) or "").strip()  # 括弧内名前、例: "久徳大輔君"
    body_first_line = (m.group(4) or "").strip()

    # 敬称除去: 君 / さん / 氏 を末尾から削除
    speaker_from_parens = re.sub(r"[君さん氏]+$", "", speaker_raw).strip()

    if speaker_from_parens:
        # 標準形式 (prefokayama): "○議長（久徳大輔君）"
        #   → speaker="久徳大輔", position="議長"
        speaker = speaker_from_parens
        position = position_raw or None
    elif position_raw:
        # 括弧なし形式 (yokohama 委員会): "○川口広委員長"
        #   group(2) 自体が氏名+役職を含む → speaker=全体、position=None
        speaker = position_raw
        position = None
    else:
        speaker = "(不明)"
        position = None

    # 本文連結 (1行目残部 + 改行以降)
    if body_first_line and rest:
        body = body_first_line + "\n" + rest.strip()
    elif body_first_line:
        body = body_first_line
    else:
        body = rest.strip()

    return speech_type, speaker, position, body


def _build_schedule_url(base_url: str, council_id: str, tenant_id_num: str | None = None) -> str:
    """L2 (MinuteSchedule.html) の URL を組み立てる。"""
    params = [f"council_id={council_id}"]
    if tenant_id_num:
        params.insert(0, f"tenant_id={tenant_id_num}")
    return f"{base_url}MinuteSchedule.html?{'&'.join(params)}"


def _build_minuteview_url(base_url: str, council_id: str, schedule_id: str) -> str:
    """L3 (MinuteView.html) の URL を組み立てる。"""
    return f"{base_url}MinuteView.html?council_id={council_id}&schedule_id={schedule_id}"


def _extract_url_param(url: str, name: str) -> str | None:
    """URL クエリから 1 パラメタを抽出。"""
    try:
        qs = parse_qs(urlparse(url).query)
        v = qs.get(name)
        return v[0] if v else None
    except Exception:  # noqa: BLE001
        return None


class KaigirokuNetClient:
    """kaigiroku.net DiscussNet の async スクレイパー (Playwright + Chromium)。

    Usage:
        async with KaigirokuNetClient(tenant_id="prefokayama") as client:
            councils = await client.list_councils()
            schedules = await client.list_schedules(councils[0].council_id)
            speeches = await client.fetch_speeches(
                councils[0].council_id, schedules[0].schedule_id
            )

    Args:
        tenant_id: テナント ID (例: prefokayama, yokohama)
        base_url: 白ラベル型用の上書き URL (None なら中央型 ssp.kaigiroku.net)
        headless: True で headless Chromium
        timeout_ms: ページ遷移 / セレクタ待機タイムアウト
        rate_limit_sec: 連続リクエスト間の待機秒数 (倫理: 自治体サーバへの礼儀)
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
        """DOM ダンプ (デバッグ + セレクタ決定用)。"""
        url = self.base_url + path
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            page_title = await page.title()

            candidate_rows = []
            for sel in COUNCIL_LIST_SELECTORS:
                try:
                    count = await page.locator(sel).count()
                    sample = ""
                    if count > 0:
                        sample = (await page.locator(sel).first.inner_text())[:120]
                    candidate_rows.append({"selector": sel, "count": count, "sample_text": sample})
                except Exception as exc:  # noqa: BLE001
                    candidate_rows.append({"selector": sel, "error": str(exc)})

            return {
                "url": url,
                "title": page_title,
                "table_count": await page.locator("table").count(),
                "body_html_length": len(await page.content()),
                "candidate_rows": candidate_rows,
            }
        finally:
            await page.close()

    async def list_councils(
        self, path: str = "MinuteBrowse.html", max_items: int = 50
    ) -> list[MeetingSummary]:
        """L1: 定例会・臨時会 一覧を取得。

        Returns:
            MeetingSummary list (council_id + 名称)。detail_url は L2 (MinuteSchedule) を指す。
        """
        url = self.base_url + path
        page = await self._new_page()
        try:
            logger.info("kaigiroku.list_councils url=%s", url)
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            await self._sleep_polite()

            # セレクタ確定
            rows_selector = await self._first_matching_selector(page, COUNCIL_LIST_SELECTORS)
            if rows_selector is None:
                logger.warning("kaigiroku.no_council_list tenant=%s url=%s", self.tenant_id, url)
                return []

            raw_rows = await page.evaluate(
                """(selector) => {
                    const rows = Array.from(document.querySelectorAll(selector));
                    return rows.slice(0, 200).map(row => ({
                        council_id: row.getAttribute('data-council_id') || row.getAttribute('data-council-id'),
                        cell_texts: Array.from(row.querySelectorAll('td')).map(c => (c.innerText || '').trim()),
                        link_text: row.querySelector('a.link-council, a.link-thema, a')?.innerText?.trim() || '',
                        row_text: (row.innerText || '').trim(),
                    }));
                }""",
                rows_selector,
            )

            # tenant_id_num を 1 回だけ取得 (link クリック後 URL から)
            tenant_id_num: str | None = None

            councils: list[MeetingSummary] = []
            for raw in raw_rows:
                if len(councils) >= max_items:
                    break
                cid = (raw.get("council_id") or "").strip()
                if not cid:
                    continue  # data-council_id が無い行 (ヘッダ等) は skip

                # 名前: link_text を優先、なければ cell の中で「定例会」「臨時会」「本会議」含むもの
                link_text = (raw.get("link_text") or "").strip()
                cells = raw.get("cell_texts") or []
                title = link_text
                if not title:
                    for cell in cells:
                        if any(kw in cell for kw in ("定例会", "臨時会", "本会議", "委員会")):
                            title = cell.strip()
                            break
                if not title:
                    title = " ".join(c for c in cells if c).strip()

                # name_of_meeting: cell の中で「本会議」「委員会」を優先
                name_of_meeting = next(
                    (
                        c.strip()
                        for c in cells
                        if any(kw in c for kw in ("本会議", "委員会", "公聴会", "審議会"))
                    ),
                    title,
                )

                # tenant_id_num を 1 度取得 (L2 URL 組み立てに必要)
                if tenant_id_num is None:
                    tenant_id_num = await self._discover_tenant_id_num(page)

                detail_url = _build_schedule_url(self.base_url, cid, tenant_id_num)

                councils.append(
                    MeetingSummary(
                        tenant_id=self.tenant_id,
                        council_id=cid,
                        name_of_meeting=name_of_meeting,
                        title=title,
                        detail_url=detail_url,
                    )
                )

            logger.info("kaigiroku.list_councils_done n=%d", len(councils))
            return councils
        finally:
            await page.close()

    async def list_schedules(
        self,
        council_id: str,
        tenant_id_num: str | None = None,
        max_items: int = 100,
    ) -> list[MeetingSchedule]:
        """L2: 1 council 配下の会議日一覧を取得。

        Args:
            council_id: L1 で得た council ID (例: "177")
            tenant_id_num: テナント内部数値 ID (L2 URL に必要、None なら自動取得)
            max_items: 最大取得件数
        """
        # tenant_id_num が無ければ 1 度 L1 を開いて取得
        if tenant_id_num is None:
            tenant_id_num = await self._fetch_tenant_id_num()

        url = _build_schedule_url(self.base_url, council_id, tenant_id_num)
        page = await self._new_page()
        try:
            logger.info("kaigiroku.list_schedules council_id=%s url=%s", council_id, url)
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            await self._sleep_polite()

            # link-minute-view が L2 のリンク
            link_selector = await self._first_matching_selector(page, SCHEDULE_LINK_SELECTORS)
            if link_selector is None:
                logger.warning("kaigiroku.no_schedule_link council_id=%s url=%s", council_id, url)
                return []

            # 各 link から (council_id, schedule_id) は data 属性 or onclick から推定
            # 直接 click すると URL 遷移するので、まず DOM から schedule_id を推測
            raw_links = await page.evaluate(
                """(selector) => {
                    const links = Array.from(document.querySelectorAll(selector));
                    return links.map((a, i) => {
                        const tr = a.closest('tr');
                        return {
                            index: i,
                            // data-schedule_id があれば優先
                            schedule_id: a.getAttribute('data-schedule_id') || tr?.getAttribute('data-schedule_id') || null,
                            // 親 tr の全 data 属性
                            tr_data: tr ? Object.fromEntries(Array.from(tr.attributes).filter(at => at.name.startsWith('data-')).map(at => [at.name, at.value])) : {},
                            link_text: (a.innerText || '').trim(),
                            tr_text: tr ? (tr.innerText || '').trim() : '',
                            page_label: tr?.querySelector('td')?.innerText?.trim() || null,
                        };
                    });
                }""",
                link_selector,
            )

            # ページ上部 council name から base_year を抽出
            council_title_text = await page.evaluate(
                """() => {
                    const el = document.querySelector('#council-title, .he-txt-minute h1, h1');
                    return el ? el.innerText.trim() : '';
                }"""
            )
            base_year = _extract_view_year_from_council_name(council_title_text)
            logger.debug(
                "kaigiroku.l2_council_title=%r base_year=%s", council_title_text, base_year
            )

            # schedule_id が data 属性で取れない場合、click → URL 取得で取得
            schedules: list[MeetingSchedule] = []

            for i, raw in enumerate(raw_links):
                if i >= max_items:
                    break
                schedule_id = raw.get("schedule_id")
                if not schedule_id:
                    # tr_data から候補抽出
                    tr_data = raw.get("tr_data") or {}
                    for key in ("data-schedule_id", "data-schedule-id", "data-id"):
                        if tr_data.get(key):
                            schedule_id = tr_data[key]
                            break
                # それでも無ければ index+1 を fallback
                if not schedule_id:
                    schedule_id = str(i + 1)

                tr_text = raw.get("tr_text") or ""
                # tr_text 例: "P.1\t02月21日－01号\t\t▼"
                parts = [p.strip() for p in tr_text.split("\t") if p.strip()]
                page_label = parts[0] if parts and parts[0].startswith("P.") else None
                title = next(
                    (p for p in parts if re.search(r"\d{1,2}月\s*\d{1,2}日", p)),
                    (raw.get("link_text") or parts[-1] if parts else "(unknown)"),
                )

                # 詳細 URL を組み立て
                detail_url = _build_minuteview_url(self.base_url, council_id, schedule_id)

                schedules.append(
                    MeetingSchedule(
                        tenant_id=self.tenant_id,
                        council_id=council_id,
                        schedule_id=str(schedule_id),
                        page_label=page_label,
                        title=title,
                        meeting_date=_parse_schedule_title_to_date(title, base_year=base_year),
                        detail_url=detail_url,
                    )
                )

            logger.info("kaigiroku.list_schedules_done n=%d", len(schedules))
            return schedules
        finally:
            await page.close()

    async def fetch_speeches(
        self,
        council_id: str,
        schedule_id: str,
        max_speeches: int = 200,
        name_of_meeting: str = "(unknown)",
    ) -> list[Speech]:
        """L3: 個別議事録から発言ブロックを抽出。

        Args:
            council_id: L1 council_id
            schedule_id: L2 schedule_id
            max_speeches: 発言上限
            name_of_meeting: 会議名 (L2 から伝播、ログ用)
        """
        url = _build_minuteview_url(self.base_url, council_id, schedule_id)
        page = await self._new_page()
        try:
            logger.info("kaigiroku.fetch_speeches url=%s", url)
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            await self._sleep_polite()

            speech_selector = await self._first_matching_selector(page, SPEECH_BLOCK_SELECTORS)
            if speech_selector is None:
                logger.warning("kaigiroku.no_speech_selector url=%s", url)
                # フォールバック: body 全文を 1 speech として返す
                body_text = await page.locator("body").inner_text()
                return [
                    Speech(
                        tenant_id=self.tenant_id,
                        council_id=council_id,
                        schedule_id=schedule_id,
                        name_of_meeting=name_of_meeting,
                        speech_order=0,
                        speaker="(全文)",
                        content_text=body_text[:5000],
                        detail_url=url,
                    )
                ]

            raw = await page.evaluate(
                """(selector) => {
                    const els = Array.from(document.querySelectorAll(selector));
                    return els.map(el => ({
                        text: (el.innerText || '').trim(),
                    }));
                }""",
                speech_selector,
            )

            # council-title (例: '岡山県　令和　７年　２月定例会　02月21日－01号') から
            # base_year + 会議日タイトルを抽出
            council_title_text = await page.evaluate(
                """() => document.querySelector('#council-title')?.innerText || ''"""
            )
            base_year = _extract_view_year_from_council_name(council_title_text)
            # 会議日タイトル (例: '02月21日－01号') を council-title 末尾から抽出
            schedule_title_match = re.search(r"(\d{1,2}月\s*\d{1,2}日[^\s]*)", council_title_text)
            schedule_title = schedule_title_match.group(1) if schedule_title_match else ""
            meeting_date = _parse_schedule_title_to_date(schedule_title, base_year=base_year)

            # name_of_meeting が default なら council-title から取得を試みる
            effective_meeting_name = name_of_meeting
            if effective_meeting_name == "(unknown)" and council_title_text:
                effective_meeting_name = council_title_text.strip()

            speeches: list[Speech] = []
            order = 0
            for r in raw:
                text = (r.get("text") or "").strip()
                if len(text) < 5:
                    continue
                speech_type, speaker, position, body = _parse_speech_block(text)
                speeches.append(
                    Speech(
                        tenant_id=self.tenant_id,
                        council_id=council_id,
                        schedule_id=schedule_id,
                        meeting_date=meeting_date,
                        name_of_meeting=effective_meeting_name,
                        speech_order=order,
                        speech_type=speech_type,
                        speaker=speaker,
                        speaker_position=position,
                        content_text=body or text,
                        detail_url=url,
                    )
                )
                order += 1
                if order >= max_speeches:
                    break

            logger.info(
                "kaigiroku.fetch_speeches_done n=%d base_year=%s meeting_date=%s",
                len(speeches),
                base_year,
                meeting_date,
            )
            return speeches
        finally:
            await page.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("KaigirokuNetClient must be used as async context manager")
        return await self._context.new_page()

    async def _first_matching_selector(self, page: Page, selectors: list[str]) -> str | None:
        for sel in selectors:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    logger.debug("kaigiroku.selector_matched selector=%r count=%d", sel, count)
                    return sel
            except Exception:  # noqa: BLE001
                continue
        return None

    async def _discover_tenant_id_num(self, page: Page) -> str | None:
        """L1 ページから tenant_id_num を抽出 (L2 URL 組み立てに使う)。

        手段:
        1. ページ HTML 内の hidden input / data 属性
        2. 最初の link-council を click → URL から抽出 → 戻る
        """
        # まず HTML 内をスキャン
        tenant_id_num = await page.evaluate(
            """() => {
                // hidden input #tenant_id 等
                const el = document.querySelector('input[name=tenant_id], input#tenant_id, [data-tenant_id]');
                if (el) return el.value || el.getAttribute('data-tenant_id');
                // body 全文から tenant_id=NNN を検索
                const m = document.body.innerHTML.match(/tenant_id[=:]['"]?(\\d+)/);
                return m ? m[1] : null;
            }"""
        )
        if tenant_id_num:
            return str(tenant_id_num)

        # フォールバック: link-council を click して URL から取得
        try:
            link = page.locator("a.link-council").first
            if await link.count() == 0:
                return None
            # ナビゲーション後の URL を取得
            await link.click()
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            new_url = page.url
            tenant_id_num = _extract_url_param(new_url, "tenant_id")
            # 戻る (L1 状態維持のため)
            await page.go_back(wait_until="networkidle", timeout=self.timeout_ms)
            return tenant_id_num
        except Exception as exc:  # noqa: BLE001
            logger.warning("kaigiroku.tenant_id_num_discovery_failed exc=%s", exc)
            return None

    async def _fetch_tenant_id_num(self) -> str | None:
        """L1 を 1 度開いて tenant_id_num のみ取得 (list_schedules の事前準備用)。"""
        page = await self._new_page()
        try:
            await page.goto(
                self.base_url + "MinuteBrowse.html",
                wait_until="networkidle",
                timeout=self.timeout_ms,
            )
            return await self._discover_tenant_id_num(page)
        finally:
            await page.close()

    async def _sleep_polite(self) -> None:
        """自治体サーバへの礼儀 (rate limit)。"""
        if self.rate_limit_sec > 0:
            await asyncio.sleep(self.rate_limit_sec)
