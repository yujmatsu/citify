"""移住支援金マッチング (TASK-SUPPORT)。

設計: docs/plans/2026-06-09-relocation-support-matching-design.md

P1: 国の移住支援金(地方創生移住支援事業)を persona+seed から**決定的に判定**(純関数・LLM不要)。
アドバイザーとして「対象の"可能性"」を教える。金額・該当は断定せず公式リンクへ誘導。

判定軸(既存 persona):
    現住所(home) … 東京23区/東京圏/それ以外
    移住先(recommended) … 国の対象自治体(seed)に参加しているか
    世帯構成(household) … 単身60万 / 世帯100万 ＋ 子加算の可能性
就業要件(対象求人就業/テレワーク継続/起業)は persona に無いため条件として併記する。
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from agents.watcher.schema import NationalSupport

logger = logging.getLogger(__name__)

# 国の移住支援金の入口(自治体公式が無い場合のフォールバック)
NATIONAL_PORTAL = "https://www.iju-join.jp/"
_REQUIREMENTS = "対象求人への就業／テレワーク継続／起業 のいずれか(移住先での就業条件)"

_SEED_PATH = Path(__file__).resolve().parent / "data" / "relocation_support.csv"
_SEED_CACHE: dict[str, dict[str, str]] | None = None


def load_support_seed(path: Path | None = None) -> dict[str, dict[str, str]]:
    """参加自治体 seed を {code: {official_url, note}} で返す (participates=true のみ・キャッシュ)。"""
    global _SEED_CACHE
    if path is None and _SEED_CACHE is not None:
        return _SEED_CACHE
    target = path or _SEED_PATH
    out: dict[str, dict[str, str]] = {}
    try:
        with target.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = (row.get("municipality_code") or "").strip().zfill(5)
                if code and (row.get("participates") or "").strip().lower() == "true":
                    out[code] = {
                        "official_url": (row.get("official_url") or "").strip(),
                        "note": (row.get("note") or "").strip(),
                    }
    except FileNotFoundError:
        logger.warning("relocation_support seed not found: %s", target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("relocation_support load failed: %s", exc)
    if path is None:
        _SEED_CACHE = out
    return out


def _home_category(code: str) -> str:
    """現住所の東京圏区分。tokyo23 / tokyo_area / other。"""
    c = (code or "").zfill(5)
    pref, rest = c[:2], c[2:]
    if pref == "13" and "101" <= rest <= "123":  # 東京23区 (13101-13123)
        return "tokyo23"
    if pref in ("11", "12", "13", "14"):  # 埼玉/千葉/東京/神奈川 = 東京圏
        return "tokyo_area"
    return "other"


def _amount_for(household: str) -> int | None:
    if household == "single":
        return 60
    if household in ("couple", "family_kids"):
        return 100
    return None  # 世帯構成未設定 → 額は範囲(単身60/世帯100)として表示側で扱う


def match_national_support(
    home_code: str,
    recommended_code: str | None,
    household: str,
    seed: dict[str, dict[str, str]] | None = None,
) -> NationalSupport:
    """国の移住支援金の対象可能性・概算額を判定 (純関数)。断定せず"可能性"を返す。"""
    lookup = seed if seed is not None else load_support_seed()
    rec = (recommended_code or "").zfill(5)
    participates = rec in lookup
    official = (lookup.get(rec, {}).get("official_url") or "") or NATIONAL_PORTAL
    is_family = household == "family_kids"

    if not participates:
        return NationalSupport(
            eligibility="unlikely",
            amount_man=None,
            child_addition=is_family,
            requirements=_REQUIREMENTS,
            official_url=official,
            note="移住先が国の移住支援金の対象自治体に含まれない可能性(東京圏や三大都市圏は対象外)。最新は公式で確認を。",
        )

    home_cat = _home_category(home_code)
    if home_cat == "other":
        return NationalSupport(
            eligibility="unlikely",
            amount_man=None,
            child_addition=is_family,
            requirements=_REQUIREMENTS,
            official_url=official,
            note="現住所が東京圏でないため、国の移住支援金は対象外の可能性。最新は公式で確認を。",
        )

    if home_cat == "tokyo23":
        eligibility = "likely"
        note = "現住所が東京23区のため対象者要件を満たす可能性が高い。"
    else:  # tokyo_area
        eligibility = "conditional"
        note = "東京圏在住のため、東京23区への通勤実績があれば対象の可能性。"

    return NationalSupport(
        eligibility=eligibility,
        amount_man=_amount_for(household),
        child_addition=is_family,
        requirements=_REQUIREMENTS,
        official_url=official,
        note=note,
    )
