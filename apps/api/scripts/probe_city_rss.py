"""Tier 3 一般市町村 (1,700+) に対する RSS feed bulk probe (Plan A-E)。

municipality_master.csv からカナ → ローマ字を生成し、複数の RSS URL パターンに対し
並列で curl を投げる。HTTP 200 + XML 形式のものを「ヒット」として記録。

ヒットしたものを `infra/seed/tier3_rss_hits.csv` に出力 (slug,muni_code,name,romaji,url)。

使用方法:
    python -m apps.api.scripts.probe_city_rss \\
        --master infra/seed/municipality_master.csv \\
        --output infra/seed/tier3_rss_hits.csv \\
        --concurrency 30 \\
        [--limit 100]  # デバッグ用、先頭 N 件のみ

URL パターン (試す順):
    1. https://www.city.{romaji}.{pref_romaji}.jp/rss.xml
    2. https://www.city.{romaji}.lg.jp/rss.xml
    3. https://www.city.{romaji}.lg.jp/news/rss.xml
    4. https://www.city.{romaji}.lg.jp/rss_news.xml
    5. https://www.city.{romaji}.lg.jp/main/rss/rss.xml
    6. https://www.city.{romaji}.lg.jp/info.rdf
    7. https://www.city.{romaji}.{pref_romaji}.jp/main/rss/rss.xml

ヒットしたら最初の 1 つを採用 (短く優先)。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# 都道府県 → ローマ字 (URL hostname の "city.{romaji}.{pref}.jp" 用)
_PREF_TO_ROMAJI: dict[str, str] = {
    "北海道": "hokkaido",
    "青森県": "aomori",
    "岩手県": "iwate",
    "宮城県": "miyagi",
    "秋田県": "akita",
    "山形県": "yamagata",
    "福島県": "fukushima",
    "茨城県": "ibaraki",
    "栃木県": "tochigi",
    "群馬県": "gunma",
    "埼玉県": "saitama",
    "千葉県": "chiba",
    "東京都": "tokyo",
    "神奈川県": "kanagawa",
    "新潟県": "niigata",
    "富山県": "toyama",
    "石川県": "ishikawa",
    "福井県": "fukui",
    "山梨県": "yamanashi",
    "長野県": "nagano",
    "岐阜県": "gifu",
    "静岡県": "shizuoka",
    "愛知県": "aichi",
    "三重県": "mie",
    "滋賀県": "shiga",
    "京都府": "kyoto",
    "大阪府": "osaka",
    "兵庫県": "hyogo",
    "奈良県": "nara",
    "和歌山県": "wakayama",
    "鳥取県": "tottori",
    "島根県": "shimane",
    "岡山県": "okayama",
    "広島県": "hiroshima",
    "山口県": "yamaguchi",
    "徳島県": "tokushima",
    "香川県": "kagawa",
    "愛媛県": "ehime",
    "高知県": "kochi",
    "福岡県": "fukuoka",
    "佐賀県": "saga",
    "長崎県": "nagasaki",
    "熊本県": "kumamoto",
    "大分県": "oita",
    "宮崎県": "miyazaki",
    "鹿児島県": "kagoshima",
    "沖縄県": "okinawa",
}


# 末尾接尾語 (URL ローマ字には含めない)
_SUFFIX_KANA = ("シ", "マチ", "ムラ", "ク", "チョウ", "ソン")


def _kana_to_romaji_with_pykakasi(kana: str) -> str:
    """pykakasi でカナ→ローマ字変換 (ヘボン式)。"""
    import pykakasi

    kks = pykakasi.kakasi()
    results = kks.convert(kana)
    return "".join(r["hepburn"] for r in results)


def _strip_suffix(kana: str) -> str:
    """末尾の「シ/マチ/ムラ/ク/チョウ/ソン」を 1 つ除去。"""
    for suf in _SUFFIX_KANA:
        if kana.endswith(suf):
            return kana[: -len(suf)]
    return kana


def _romaji_from_master(kana: str) -> str:
    """カナからローマ字を推定。

    1. 末尾の接尾語 (シ/マチ/ムラ/ク/チョウ/ソン) を除去
    2. pykakasi でヘボン式に変換
    3. 小文字 + 記号除去
    """
    if not kana:
        return ""
    stripped = _strip_suffix(kana)
    romaji = _kana_to_romaji_with_pykakasi(stripped)
    return re.sub(r"[^a-zA-Z]", "", romaji).lower()


def _url_patterns(romaji: str, pref_romaji: str) -> list[str]:
    """1 自治体に対する RSS URL 候補リスト (短く高ヒット率のものから順)。"""
    # `.lg.jp` 系を優先 (政令市・中核市で実証パターン)
    # `.{pref_romaji}.jp` 系は地方都市で多い
    return [
        f"https://www.city.{romaji}.lg.jp/rss.xml",
        f"https://www.city.{romaji}.{pref_romaji}.jp/rss.xml",
        f"https://www.city.{romaji}.lg.jp/news/rss.xml",
        f"https://www.city.{romaji}.lg.jp/main/rss/rss.xml",
        f"https://www.city.{romaji}.lg.jp/rss_news.xml",
        f"https://www.city.{romaji}.lg.jp/info.rdf",
        f"https://www.city.{romaji}.{pref_romaji}.jp/main/rss/rss.xml",
        f"https://www.town.{romaji}.{pref_romaji}.jp/rss.xml",
        f"https://www.town.{romaji}.lg.jp/rss.xml",
        f"https://www.village.{romaji}.{pref_romaji}.jp/rss.xml",
    ]


async def _probe_one_url(client, url: str, request_timeout: float = 6.0) -> int:
    """HEAD ではなく軽量 GET で probe (一部サーバは HEAD を rejects する)。"""
    try:
        resp = await client.get(url, timeout=request_timeout, follow_redirects=True)
        if resp.status_code != 200:
            return resp.status_code
        # XML らしさを軽くチェック (item or entry タグの存在)
        body = resp.text[:2048]
        if "<item" in body or "<entry" in body or "<rdf:" in body.lower():
            return 200
        return 422  # 200 だが XML でない (HTML エラーページ等)
    except Exception:  # noqa: BLE001
        return 0  # connection failed


async def _probe_municipality(
    client,
    sem: asyncio.Semaphore,
    muni_code: str,
    romaji: str,
    pref_romaji: str,
) -> tuple[str, str | None]:
    """1 自治体の URL 候補を順次 probe、最初にヒットしたものを返す。

    並列ではなく順次 (1 自治体内では): 短く高頻度なものから試して早期 break。
    """
    if not romaji or not pref_romaji:
        return muni_code, None
    async with sem:
        for url in _url_patterns(romaji, pref_romaji):
            status = await _probe_one_url(client, url)
            if status == 200:
                return muni_code, url
        return muni_code, None


async def probe_all(
    municipalities: list[dict[str, str]],
    concurrency: int,
    request_timeout: float,
) -> list[dict[str, str]]:
    """全自治体を並列 probe、ヒット結果を dict のリストで返す。"""
    import httpx

    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": "Citify-Bulk-Probe/1.0 (Hackathon)"}

    async with httpx.AsyncClient(headers=headers, timeout=request_timeout) as client:
        tasks = []
        for m in municipalities:
            pref_romaji = _PREF_TO_ROMAJI.get(m["prefecture"], "")
            if not pref_romaji:
                continue
            romaji = _romaji_from_master(m["kana"])
            if not romaji:
                continue
            tasks.append(
                _probe_municipality(client, sem, m["municipality_code"], romaji, pref_romaji)
            )
        hits: list[dict[str, str]] = []
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            muni_code, url = await coro
            if url:
                # name と romaji は元の dict から再 lookup
                m = next(
                    (mm for mm in municipalities if mm["municipality_code"] == muni_code), None
                )
                if m:
                    hits.append(
                        {
                            "municipality_code": muni_code,
                            "name": m["name"],
                            "prefecture": m["prefecture"],
                            "rss_url": url,
                        }
                    )
                    logger.info(
                        "probe.hit n=%d muni=%s name=%s url=%s",
                        len(hits),
                        muni_code,
                        m["name"],
                        url,
                    )
            if (i + 1) % 100 == 0:
                logger.info("probe.progress %d/%d processed, %d hits", i + 1, len(tasks), len(hits))
    return hits


def load_municipalities(master_csv: Path, limit: int | None = None) -> list[dict[str, str]]:
    """municipality_master.csv を読み込む (国会 + 都道府県集約行は除外)。"""
    result: list[dict[str, str]] = []
    with master_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("municipality_code") or "").strip()
            name = (row.get("name") or "").strip()
            pref = (row.get("prefecture") or "").strip()
            kana = (row.get("kana") or "").strip()
            notes = (row.get("notes") or "").strip()
            if not code or not name:
                continue
            if code == "00000":  # 国会は除外
                continue
            if "prefecture_aggregate" in notes:  # 都道府県集約行は除外
                continue
            if pref == "国":
                continue
            result.append(
                {
                    "municipality_code": code,
                    "name": name,
                    "prefecture": pref,
                    "kana": kana,
                }
            )
            if limit and len(result) >= limit:
                break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Tier 3 一般市町村 RSS bulk probe")
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("infra/seed/municipality_master.csv"),
        help="自治体マスタ CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("infra/seed/tier3_rss_hits.csv"),
        help="ヒット結果出力 CSV",
    )
    parser.add_argument("--concurrency", type=int, default=30, help="並列数 (default 30)")
    parser.add_argument(
        "--timeout", type=float, default=6.0, help="リクエスト timeout 秒 (default 6.0)"
    )
    parser.add_argument("--limit", type=int, default=None, help="先頭 N 件のみ probe (デバッグ用)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    munis = load_municipalities(args.master, limit=args.limit)
    logger.info("loaded %d municipalities from %s", len(munis), args.master)

    hits = asyncio.run(probe_all(munis, args.concurrency, request_timeout=args.timeout))
    logger.info("probe.complete total_hits=%d (%.1f%%)", len(hits), 100 * len(hits) / len(munis))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["municipality_code", "name", "prefecture", "rss_url"]
        )
        writer.writeheader()
        writer.writerows(sorted(hits, key=lambda h: h["municipality_code"]))
    print(f"# Wrote {len(hits)} hits to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
