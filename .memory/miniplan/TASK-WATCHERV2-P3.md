# ミニプラン: Watcher v2 P3 — マルチエージェント化(専門家4 + Synthesizer)

## 概要
- **タスクID**: TASK-WATCHERV2-P3(設計: docs/plans/2026-06-07-agent-autonomy-v2-design.md §2/§8 P3、A5)
- **目的**: 単一エージェントの draft を **4専門エージェントの並行調査 → Synthesizer 統合**に置換。
  「マルチエージェント AI プロダクト」をテーマ通り実体化(①最大化)。P2の Critic/Advocate はそのまま後段に。
- **完了条件**:
  1. 4専門家(人口/財政/暮らし・治安/議題)が**並行**で各ドメインを調査し SpecialistFinding を返す
  2. Synthesizer が4所見を統合し TownAnalysis 草案を生成 → P2(Critique+Advocate+Revise)を適用
  3. tool_calls は全専門家分を集約(チームの自律証跡)。/agent に「👥 専門家の所見」表示
  4. レイテンシは並行化で bound(300s 以内)、pytest green / ruff / tsc / build
  5. 倫理ゲート・graceful(専門家失敗は欠落として続行)維持

## 設計(オーケストレーションは Python = 決定的・テスト可能、ADK層は薄く)
```
run():
  1. 並行ディスパッチ: asyncio.gather(_run_specialist(d) for d in DOMAINS)  # 4専門家
       各 _run_specialist = ツール付き ADK エージェント(ドメイン別 instruction + tool 部分集合)
       → SpecialistFinding{domain, headline, key_points[], confidence, source_speech_ids[]}
       各専門家のツール上限 = 4(暴走防止)
  2. Synthesize: _run_single_agent(SYNTHESIZER_PROMPT, findings_json + context) → TownAnalysis 草案
  3. P2: critique + 悪魔の代弁者(並列) → 必要なら revise (既存 _verify_and_revise を流用)
  4. specialist_findings を analysis に付与(透明性)、tool_calls 集約、persist
```
ドメイン→ツール:
- 人口: fetch_population_trend, compare_towns
- 財政: compare_towns
- 暮らし・治安: compare_towns
- 議題: search_speeches, fetch_topic_trend

## 作業ステップ
1. [ ] schema: `SpecialistFinding` + TownAnalysis に `specialist_findings: list[SpecialistFinding]`
2. [ ] prompts: `SPECIALIST_INSTRUCTIONS`(4ドメイン)+ `build_specialist_prompt` + `SYNTHESIZER_PROMPT` + `build_synth_prompt`
3. [ ] main.py: `parse_finding`(純関数)/ `_build_specialist_agent` / `_run_specialist` / `_synthesize` / run() 再構成
4. [ ] UI: /agent に「👥 専門エージェントの所見」(ドメイン別カード)+ api.ts に specialist_findings
5. [ ] テスト(parse_finding / run orchestration を specialist・single_agent mock で)+ 検証
6. [ ] 実環境 smoke(deployed)で 並行起動・レイテンシ・status=ok 確認

## リスク
| リスク | 対策 |
|---|---|
| 並行ADK Runner の不安定/レイテンシ | 各専門家に独立 session、gather で並行、tool上限4。総レイテンシは max(専門家)+synth+P2 |
| compare_towns 重複呼出(3専門家) | 並行 + BQ 軽量なので許容。必要なら後で共有 prefetch 化 |
| テスト不能(実ADK) | parse_finding 純関数 + _run_specialist/_run_single_agent を mock してオーケストレーション検証 |
| 草案が空(専門家全滅) | 1人でも finding があれば synthesize。全滅なら status=empty(既存 graceful) |
| レイテンシ増で 504 | timeout 300s 済 + 並行化。P5 日次事前計算で体感解消 |
