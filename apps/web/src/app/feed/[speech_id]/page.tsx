"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  clearReaction,
  fetchReaction,
  fetchReactionSummary,
  fetchRelated,
  fetchSpeech,
  REACTION_VALUES,
  setReaction as putReaction,
  type FeedItem,
  type Reaction,
  type ReactionSummary,
  type RelatedResponse,
} from "@/lib/api";
import {
  findByCode,
  formatMunicipalityLabel,
  loadMunicipalities,
  type Municipality,
} from "@/lib/municipalities";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

type State =
  | { kind: "loading" }
  | { kind: "ok"; item: FeedItem; persona: Persona }
  | { kind: "error"; message: string };


function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, (value / 25) * 100));
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-zinc-500">
        <span>{label}</span>
        <span>{value} / 25</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function SpeechDetailPage() {
  const params = useParams<{ speech_id: string }>();
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [reaction, setReactionState] = useState<Reaction | null>(null);
  const [reactionPending, setReactionPending] = useState(false);
  const [reactionError, setReactionError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ReactionSummary | null>(null);
  const [municipalities, setMunicipalities] = useState<Municipality[] | null>(null);
  const [related, setRelated] = useState<
    | { kind: "loading" }
    | { kind: "ok"; data: RelatedResponse }
    | { kind: "error"; message: string }
    | { kind: "no_corpus" }
  >({ kind: "loading" });

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      router.replace("/onboarding");
      return;
    }
    const sid = decodeURIComponent(params.speech_id);
    let cancelled = false;

    // 自治体マスタを並行ロード (cache あり、複数ページで共有)
    loadMunicipalities()
      .then((m) => {
        if (cancelled) return;
        setMunicipalities(m);
      })
      .catch(() => setMunicipalities([]));

    // 主データ (speech 詳細) を先に取得
    fetchSpeech(sid, persona.user_id)
      .then((item) => {
        if (cancelled) return;
        setState({ kind: "ok", item, persona });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });

    // RAG 関連議題は並行で取得 (失敗してもメインは表示)
    fetchRelated(sid, persona.user_id, 3)
      .then((data) => {
        if (cancelled) return;
        if (!data.corpus_used) {
          setRelated({ kind: "no_corpus" });
        } else {
          setRelated({ kind: "ok", data });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setRelated({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });

    // 既存のリアクション状態を取得 (失敗時は静かに無視 = 未設定扱い)
    fetchReaction(sid, persona.user_id)
      .then((res) => {
        if (cancelled) return;
        setReactionState(res.reaction);
      })
      .catch(() => {
        // Firestore 未構築や認証エラー時は単に「未設定」として扱う
      });

    // リアクション集計 (Phase X+1) を並行で取得
    fetchReactionSummary(sid)
      .then((s) => {
        if (cancelled) return;
        setSummary(s);
      })
      .catch(() => {
        // 集計取得失敗時は badge 非表示 (致命的でない)
      });

    return () => {
      cancelled = true;
    };
  }, [params.speech_id, router]);

  function applySummaryDelta(
    prev: ReactionSummary | null,
    previous: Reaction | null,
    next: Reaction | null,
  ): ReactionSummary | null {
    if (!prev) return prev;
    const counts = { ...prev.counts };
    let total = prev.total;
    if (previous && counts[previous] != null) {
      counts[previous] = Math.max(0, counts[previous] - 1);
    }
    if (next && counts[next] != null) {
      counts[next] = counts[next] + 1;
    }
    // total: 新規追加 (previous=null, next≠null) で +1、解除 (previous≠null, next=null) で -1、上書きは 0
    if (!previous && next) total = total + 1;
    if (previous && !next) total = Math.max(0, total - 1);
    return { ...prev, counts, total };
  }

  async function handleReactionClick(target: Reaction): Promise<void> {
    if (state.kind !== "ok" || reactionPending) return;
    const persona = state.persona;
    const sid = decodeURIComponent(params.speech_id);
    const previous = reaction;
    const next: Reaction | null = previous === target ? null : target;

    // 楽観更新 (reaction + summary 両方)
    const summarySnapshot = summary;
    setReactionState(next);
    setSummary((s) => applySummaryDelta(s, previous, next));
    setReactionPending(true);
    setReactionError(null);
    try {
      if (next === null) {
        await clearReaction(sid, persona.user_id);
      } else {
        await putReaction(sid, persona.user_id, next);
      }
    } catch (err) {
      // 失敗時は両方ロールバック
      setReactionState(previous);
      setSummary(summarySnapshot);
      setReactionError(err instanceof Error ? err.message : String(err));
    } finally {
      setReactionPending(false);
    }
  }

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">議題が見つかりません</h1>
          <p className="text-sm text-zinc-500">{state.message}</p>
          <Link
            href="/feed"
            className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            フィードに戻る
          </Link>
        </div>
      </main>
    );
  }

  const { item } = state;
  const muniRecord =
    municipalities && item.municipality_code
      ? findByCode(municipalities, item.municipality_code)
      : undefined;
  const muni = muniRecord
    ? formatMunicipalityLabel(muniRecord)
    : (item.municipality_code ?? "—");

  return (
    <main className="flex flex-1 flex-col px-6 pb-24 pt-6 sm:px-10 sm:py-10">
      <div className="mx-auto w-full max-w-2xl space-y-8">
        {/* Top nav */}
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            {muni}
            {item.meeting_date ? ` · ${item.meeting_date}` : ""}
          </span>
        </div>

        {/* Title (翻訳タイトル) + 会議名 (正式タイトル代替) */}
        <header className="space-y-3">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            {item.title || "(タイトル未生成)"}
          </h1>
          {item.name_of_meeting && (
            <p className="text-sm text-zinc-500">
              <span className="font-medium">正式会議名:</span>{" "}
              {item.name_of_meeting}
            </p>
          )}
        </header>

        {/* Summary (3 行) */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-500">
            かいつまんで言うと
          </h2>
          <ul className="space-y-2 text-base leading-relaxed">
            {item.summary.length > 0 ? (
              item.summary.map((line, i) => (
                <li key={i} className="flex gap-3">
                  <span className="text-zinc-400">L{i + 1}</span>
                  <span>{line}</span>
                </li>
              ))
            ) : (
              <li className="text-zinc-500">(要約未生成)</li>
            )}
          </ul>
          {item.tone && (
            <p className="pt-2 text-xs text-zinc-400">tone: {item.tone}</p>
          )}
        </section>

        {/* Score breakdown */}
        <section className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-zinc-500">
              あなたへの関連度
            </h2>
            <div className="text-3xl font-bold">
              {item.relevance_score}
              <span className="text-base font-normal text-zinc-500">
                {" "}
                / 100
              </span>
            </div>
          </div>
          <div className="space-y-3">
            <ScoreBar label="トピック関連性" value={item.score_topic} />
            <ScoreBar label="年代適合性" value={item.score_age} />
            <ScoreBar label="地理関連性" value={item.score_geographic} />
            <ScoreBar label="緊急性" value={item.score_urgency} />
          </div>
          {item.matched_interests.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-2">
              {item.matched_interests.map((interest) => (
                <span
                  key={interest}
                  className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                >
                  #{interest}
                </span>
              ))}
            </div>
          )}
          {item.reasoning && (
            <p className="border-t border-zinc-200 pt-3 text-xs text-zinc-500 dark:border-zinc-800">
              <span className="font-medium">AI 採点理由:</span> {item.reasoning}
            </p>
          )}
        </section>

        {/* Plan N: 議論タイムライン動線 (Reviewer High #3: RAG 関連議題と差別化) */}
        {item.matched_interests.length > 0 && (
          <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold text-blue-900 dark:text-blue-100">
                🕰 議論の流れを見る
              </h2>
              <span className="text-[10px] text-blue-700 dark:text-blue-300">Plan N</span>
            </div>
            <p className="mt-1 text-xs text-blue-700 dark:text-blue-300">
              この interest 軸の議論変遷を Agent が物語化、5-10 マイルストーンで表示します。
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {item.matched_interests.slice(0, 3).map((interest) => {
                const params = new URLSearchParams({
                  theme_interest: interest,
                });
                if (item.municipality_code) {
                  params.set("municipality_code", item.municipality_code);
                }
                return (
                  <Link
                    key={interest}
                    href={`/timeline?${params.toString()}`}
                    className="rounded-full bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
                  >
                    {interest} ({item.municipality_code ? "この自治体" : "全国"})
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {/* RAG 検索結果 (Vertex AI RAG Engine、国会会議録 corpus に対する semantic search) */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-zinc-500">
              🔗 関連議題 (この発言の周辺、RAG semantic search)
            </h2>
            <span className="text-[10px] text-zinc-400">Vertex AI</span>
          </div>

          {related.kind === "loading" && (
            <p className="text-xs text-zinc-500">関連議題を検索中...</p>
          )}

          {related.kind === "no_corpus" && (
            <p className="text-xs text-zinc-400">
              関連議題は現在検索できません (corpus 未構築)
            </p>
          )}

          {related.kind === "error" && (
            <p className="text-xs text-rose-500">
              関連議題の取得に失敗: {related.message}
            </p>
          )}

          {related.kind === "ok" && related.data.items.length === 0 && (
            <p className="text-xs text-zinc-500">関連議題は見つかりませんでした</p>
          )}

          {related.kind === "ok" && related.data.items.length > 0 && (
            <>
              <ol className="space-y-3">
                {related.data.items.map((ctx, i) => (
                  <li
                    key={i}
                    className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-800"
                  >
                    <div className="mb-1 flex items-center justify-between text-[10px] text-zinc-400">
                      <span>#{i + 1}</span>
                      {ctx.distance != null && (
                        <span title="cosine distance (0=完全一致)">
                          類似度 {(1 - ctx.distance).toFixed(2)}
                        </span>
                      )}
                    </div>
                    <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
                      {ctx.text.length > 200 ? ctx.text.slice(0, 200) + "…" : ctx.text}
                    </p>
                    {ctx.source_uri && (
                      <p className="mt-1 break-all text-[10px] text-zinc-400">
                        📎 {ctx.source_uri}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
              <p className="text-[10px] text-zinc-400">
                ⚠️ AI による意味的検索結果です。正確性は原典でご確認ください。
              </p>
            </>
          )}
        </section>

        {/* Reactions (Phase X: Firestore 永続化) */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-zinc-500">あなたの反応</h2>
            {reactionPending && (
              <span className="text-[10px] text-zinc-400">保存中...</span>
            )}
          </div>
          <div className="flex gap-3">
            {REACTION_VALUES.map((r) => {
              const count = summary?.counts[r] ?? 0;
              return (
                <button
                  key={r}
                  type="button"
                  disabled={reactionPending}
                  onClick={() => handleReactionClick(r)}
                  className={cn(
                    "flex h-14 flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl border text-2xl leading-none transition-colors",
                    reaction === r
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
                      : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-500",
                    reactionPending && "cursor-not-allowed opacity-60",
                  )}
                  aria-pressed={reaction === r}
                  aria-label={`${r} 件数 ${count}`}
                >
                  <span>{r}</span>
                  <span
                    className={cn(
                      "text-[10px] font-medium tabular-nums",
                      count > 0
                        ? "text-zinc-600 dark:text-zinc-300"
                        : "text-zinc-400 dark:text-zinc-600",
                    )}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
          {reaction && !reactionError && (
            <p className="text-xs text-zinc-500">
              {reaction} を保存しました (もう一度押すと解除)
            </p>
          )}
          {reactionError && (
            <p className="text-xs text-rose-500">
              保存に失敗しました: {reactionError}
            </p>
          )}
        </section>

        {/* 原典リンク (必須、PROJECT.md §5) */}
        {item.detail_url && (
          <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-500">原典</h2>
            <a
              href={item.detail_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block break-all text-sm text-blue-600 underline hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
            >
              {item.detail_url} ↗
            </a>
            <p className="text-xs text-zinc-400">
              ⚠️ 必ず原典で確認してください。AI
              翻訳は要約のみで、正確性は保証されません。
            </p>
          </section>
        )}

        {/* 倫理表記 */}
        <p className="pb-8 text-center text-[10px] text-zinc-500">
          AI が説明用に翻訳・採点しました。投票推奨・政治的判断は含みません。
        </p>
      </div>
    </main>
  );
}
