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

from agents._shared.forbidden import find_forbidden_matches
from agents.watcher.schema import LocalSupport, NationalSupport

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


# ============================================================================
# P2: 自治体独自支援 (google_search グラウンディング抽出、agentic)
# ============================================================================

_LOCAL_MODEL = "gemini-2.5-flash"
_LOCAL_LOCATION = "us-central1"
_LOCAL_CACHE: dict[str, list[LocalSupport]] = {}


def _ensure_vertex_env() -> None:
    """ADK が Vertex を使うよう明示 (extract_preferences と同方針)。"""
    import os

    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", _LOCAL_LOCATION)
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev"))


def _build_local_prompt(name: str) -> str:
    return (
        f"{name}に移住・定住する人向けの**公的な支援制度**(移住支援金・子育て支援・住宅補助・"
        "起業支援など)を、最新の公式情報をWeb検索で調べて最大3件挙げてください。\n"
        "各制度を1行ずつ『制度名｜一言概要』の形式で書く(全角縦棒｜区切り)。\n"
        "金額は断定せず概要に留める。確実でない情報は出さない。"
        "政治的判断・処方・投票推奨は含めない。前置きや結びの文は不要、箇条書きのみ。"
    )


def _parse_local_lines(text: str, sources: list[str]) -> list[LocalSupport]:
    """『制度名｜概要』行を LocalSupport に。倫理スキャンで違反行は除去。最大3件。"""
    out: list[LocalSupport] = []
    official = sources[0] if sources else ""
    src = sources[0] if sources else ""
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-・*0123456789. ").strip()
        if not line or ("｜" not in line and "|" not in line):
            continue
        sep = "｜" if "｜" in line else "|"
        nm, _, summary = line.partition(sep)
        nm, summary = nm.strip(), summary.strip()
        if not nm or find_forbidden_matches(line):
            continue
        out.append(LocalSupport(name=nm, summary=summary, official_url=official, source_url=src))
        if len(out) >= 3:
            break
    return out


async def extract_local_support(
    name: str, code: str, model: str = _LOCAL_MODEL
) -> list[LocalSupport]:
    """自治体独自支援を google_search グラウンディングで抽出 (code でキャッシュ・graceful)。"""
    if code in _LOCAL_CACHE:
        return _LOCAL_CACHE[code]
    _ensure_vertex_env()

    sources: list[str] = []
    final_text = ""
    try:
        import uuid

        import google.genai.types as gat
        from google.adk import Agent, Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools import google_search

        agent = Agent(
            name="local_support_search",
            model=model,
            instruction="移住者向けの公的支援制度を Web 検索で調べて簡潔に答えるアシスタント。",
            tools=[google_search],
        )
        runner = Runner(
            agent=agent, app_name="local_support", session_service=InMemorySessionService()
        )
        sid = uuid.uuid4().hex[:8]
        await runner.session_service.create_session(
            app_name="local_support", user_id="aux", session_id=sid
        )
        msg = gat.Content(role="user", parts=[gat.Part(text=_build_local_prompt(name))])
        async for event in runner.run_async(user_id="aux", session_id=sid, new_message=msg):
            # グラウンディング出典 (web.uri) を収集 (防御的に getattr)
            gm = getattr(event, "grounding_metadata", None)
            for chunk in getattr(gm, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None)
                if uri and uri not in sources:
                    sources.append(uri)
            if getattr(event, "is_final_response", lambda: False)() and event.content:
                final_text = event.content.parts[0].text or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_local_support failed code=%s err=%s", code, exc)
        return []

    result = _parse_local_lines(final_text, sources)
    _LOCAL_CACHE[code] = result
    return result
