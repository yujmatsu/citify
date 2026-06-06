"""WatcherAgent の純粋ロジック test (TASK-WATCHER Slice 1)。

ADK Runner I/O (自律ループ) は実環境 smoke で検証するため、ここでは ADK 非依存の
parse_discoveries / apply_ethics / run-log / schema を検証する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.watcher.main import WatcherAgent, apply_ethics, parse_discoveries
from agents.watcher.schema import AgentRunLog, Discovery, WatchInput


def _disc(code="11227", title="新保育補助", why="子育て関心に合致", political=False) -> Discovery:
    return Discovery(
        municipality_code=code,
        title=title,
        summary=["保育料の補助が拡充される"],
        why_surfaced=why,
        significance="high",
        source_speech_ids=["sp-1"],
        contains_political_judgment=political,
    )


# ============================================================================
# WatchInput.all_codes
# ============================================================================


def test_all_codes_dedup_home_first() -> None:
    w = WatchInput(
        user_id="demo-40-49",
        age_group="40-49",
        interests=["子育て"],
        home_municipality_code="11227",
        watched_codes=["13104", "11227", "27100"],  # 11227 重複
    )
    assert w.all_codes() == ["11227", "13104", "27100"]  # home 先頭・重複除去


def test_all_codes_truncates_to_max5() -> None:
    # home + 6 watched = 7 → 上限5に truncate (ValidationError でなく graceful)
    w = WatchInput(
        user_id="u",
        age_group="40-49",
        home_municipality_code="00001",
        watched_codes=["00002", "00003", "00004", "00005", "00006", "00007"],
    )
    codes = w.all_codes()
    assert len(codes) == 5
    assert codes[0] == "00001"  # home は残る


# ============================================================================
# parse_discoveries
# ============================================================================


def test_parse_valid_json() -> None:
    text = (
        '{"discoveries":[{"municipality_code":"11227","title":"新保育補助",'
        '"summary":["補助拡充"],"why_surfaced":"子育て関心に合致","significance":"high",'
        '"source_speech_ids":["sp-1"],"contains_political_judgment":false}]}'
    )
    ds = parse_discoveries(text)
    assert len(ds) == 1
    assert ds[0].municipality_code == "11227"
    assert ds[0].significance == "high"


def test_parse_json_with_surrounding_text() -> None:
    text = 'はい、調査しました:\n{"discoveries": []}\n以上です。'
    assert parse_discoveries(text) == []


def test_parse_invalid_json_returns_empty() -> None:
    assert parse_discoveries("これはJSONではありません") == []
    assert parse_discoveries("") == []


def test_parse_caps_at_max_discoveries() -> None:
    import json

    payload = {
        "discoveries": [
            {
                "municipality_code": "11227",
                "title": f"t{i}",
                "summary": [],
                "why_surfaced": "w",
                "significance": "low",
                "source_speech_ids": [],
            }
            for i in range(6)
        ]
    }
    ds = parse_discoveries(json.dumps(payload))
    assert len(ds) == 3  # MAX_DISCOVERIES


def test_parse_skips_invalid_discovery() -> None:
    # significance が不正な要素は skip、正常な1件のみ残る
    text = (
        '{"discoveries":[{"municipality_code":"11227","title":"ok","summary":[],'
        '"why_surfaced":"w","significance":"high","source_speech_ids":[]},'
        '{"municipality_code":"13104","title":"bad","significance":"INVALID"}]}'
    )
    ds = parse_discoveries(text)
    assert len(ds) == 1
    assert ds[0].title == "ok"


# ============================================================================
# apply_ethics (倫理ゲート)
# ============================================================================


def test_ethics_keeps_clean_discovery() -> None:
    out = apply_ethics([_disc()])
    assert len(out) == 1


def test_ethics_drops_forbidden_pattern() -> None:
    # "必ず投票" は FORBIDDEN_PATTERNS にマッチ → surface しない
    bad = _disc(why="この政策には必ず投票しましょう")
    assert apply_ethics([bad]) == []


def test_ethics_drops_self_flagged_political() -> None:
    bad = _disc(political=True)  # LLM 自己申告で政治的判断あり
    assert apply_ethics([bad]) == []


def test_ethics_mixed_keeps_only_clean() -> None:
    clean = _disc(code="11227", title="保育補助")
    bad = _disc(code="13104", title="絶対に賛成すべき議案")  # "絶対に賛成" マッチ
    out = apply_ethics([clean, bad])
    assert [d.municipality_code for d in out] == ["11227"]


# ============================================================================
# _persist (Slice 2: repo 注入で永続化、None なら skip)
# ============================================================================


def test_persist_skips_when_no_repo() -> None:
    agent = WatcherAgent(repo=None)
    # repo=None でも例外なく no-op
    agent._persist("u", AgentRunLog(run_id="r1", user_id="u"), [_disc()])


def test_persist_calls_repo() -> None:
    repo = MagicMock()
    agent = WatcherAgent(repo=repo)
    log = AgentRunLog(run_id="r1", user_id="demo-40-49")
    discoveries = [_disc()]
    agent._persist("demo-40-49", log, discoveries)
    repo.save_run.assert_called_once_with(log)
    repo.save_discoveries.assert_called_once_with("demo-40-49", "r1", discoveries)


def test_persist_graceful_on_repo_failure() -> None:
    repo = MagicMock()
    repo.save_run.side_effect = RuntimeError("firestore down")
    agent = WatcherAgent(repo=repo)
    # repo 障害でも例外を投げない
    agent._persist("u", AgentRunLog(run_id="r1", user_id="u"), [_disc()])
