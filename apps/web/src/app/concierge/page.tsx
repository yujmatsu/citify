"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  ApiError,
  fetchConciergeHistory,
  postConcierge,
  type ConciergeHistoryItem,
  type ConciergeResponse,
  type MunicipalityCandidate,
  type ToolCallLog,
} from "@/lib/api";
import { ReasoningExplainerButton } from "@/components/reasoning-explainer";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

// 会話ターン (= 1 つの user message + 1 つの concierge response のペア)
type ChatTurn =
  | { kind: "user"; message: string; timestamp: number }
  | {
      kind: "agent";
      response: ConciergeResponse;
      timestamp: number;
      durationMs: number;
    }
  | { kind: "loading"; timestamp: number };

// プリセット質問例 (デモ用、ペルソナ 3 種)
const SAMPLE_QUESTIONS = [
  "26歳、リモートワーク、子育て予定です。家賃 5000 万円以下、保育園充実な街は?",
  "介護で実家(大分市)に戻る 34 歳です。東京の家賃が苦しい、医療機関多めで住みやすい街教えて",
  "30 歳ワーママです。保育園待機児童 2 年待ちで詰みました。保育園に確実に入れる街を教えて",
];

export default function ConciergePage() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Plan L+LL: 履歴 modal state
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [historyItems, setHistoryItems] = useState<ConciergeHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    const p = loadPersona();
    if (!p) {
      router.replace("/onboarding");
      return;
    }
    setPersona(p);
  }, [router]);

  // 新しい turn が追加されたら下にスクロール
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [turns]);

  async function handleSubmit(): Promise<void> {
    const message = input.trim();
    if (!message || !persona || isLoading) return;

    const startedAt = Date.now();
    setIsLoading(true);
    setInput("");

    // user turn を即座に追加
    setTurns((prev) => [
      ...prev,
      { kind: "user", message, timestamp: startedAt },
      { kind: "loading", timestamp: startedAt },
    ]);

    try {
      const response = await postConcierge({
        message,
        persona: {
          user_id: persona.user_id,
          age_group: persona.age_group,
          interests: persona.interests,
          municipality_codes: persona.municipality_codes,
          // TASK-ONBOARDING: 前提整理を Concierge に渡す
          priorities: persona.priorities,
          household: persona.household ?? "",
          budget_man: persona.budget_man,
          area_pref: persona.area_pref,
          free_form_context: persona.free_form_context,
        },
      });
      const durationMs = Date.now() - startedAt;
      setTurns((prev) => {
        // loading を削除して agent turn に置換
        const withoutLoading = prev.filter((t) => t.kind !== "loading");
        return [
          ...withoutLoading,
          { kind: "agent", response, timestamp: Date.now(), durationMs },
        ];
      });
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `API エラー (${err.status}): ${err.message}`
          : err instanceof Error
            ? err.message
            : "予期せぬエラーが発生しました";
      const durationMs = Date.now() - startedAt;
      setTurns((prev) => {
        const withoutLoading = prev.filter((t) => t.kind !== "loading");
        return [
          ...withoutLoading,
          {
            kind: "agent",
            response: {
              reply: `❌ ${msg}\n\n少し時間を置いて再度お試しください。`,
              tool_calls: [],
              candidates: [],
              ethical_violations: ["client_error"],
            },
            timestamp: Date.now(),
            durationMs,
          },
        ];
      });
    } finally {
      setIsLoading(false);
    }
  }

  function handleReset(): void {
    if (isLoading) return;
    if (turns.length === 0) return;
    if (!confirm("会話履歴を消して新しい相談を始めますか?")) return;
    setTurns([]);
    setInput("");
  }

  function handleSampleClick(sample: string): void {
    if (isLoading) return;
    setInput(sample);
  }

  async function handleOpenHistory(): Promise<void> {
    if (!persona || historyLoading) return;
    setIsHistoryOpen(true);
    setHistoryError(null);
    setHistoryLoading(true);
    try {
      const res = await fetchConciergeHistory(persona.user_id, 20);
      setHistoryItems(res.items);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `履歴取得失敗 (${err.status}): ${err.message}`
          : err instanceof Error
            ? err.message
            : "予期せぬエラーが発生しました";
      setHistoryError(msg);
      setHistoryItems([]);
    } finally {
      setHistoryLoading(false);
    }
  }

  function handleSelectHistoryItem(item: ConciergeHistoryItem): void {
    setInput(item.message);
    setIsHistoryOpen(false);
  }

  // SSR / hydration 中
  if (persona === null) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col px-6 pb-6 pt-6 sm:px-10">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col space-y-6">
        {/* Top nav */}
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            Citify Concierge (Plan E)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            🤖 街診断コンシェルジュ
          </h1>
          <p className="text-sm text-zinc-500">
            マイ街エージェントの結論を、対話でさらに深掘り。あなたの状況に合う自治体を
            人口・**財政力**・子育て・住居などから AI が診断します。年代 / 関心軸 / 予算 /
            家族構成を自然言語で伝えてください。
          </p>
          <Link
            href="/agent"
            className="inline-block text-xs text-emerald-600 underline hover:text-emerald-800 dark:text-emerald-400"
          >
            ← マイ街エージェント(住み続ける?移る?)に戻る
          </Link>
        </header>

        {/* チャット履歴 */}
        <div
          ref={scrollRef}
          className="flex-1 min-h-[400px] max-h-[60vh] overflow-y-auto rounded-2xl border border-zinc-200 bg-white p-4 space-y-4 dark:border-zinc-800 dark:bg-zinc-900"
        >
          {turns.length === 0 && (
            <div className="space-y-4">
              <div className="text-center py-8 text-zinc-500 text-sm">
                💬 質問を入力するか、下のサンプルをクリックしてください
              </div>
              <div className="space-y-2">
                <div className="text-xs text-zinc-500 font-semibold">
                  サンプル質問 (デモ用)
                </div>
                {SAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => handleSampleClick(q)}
                    className="block w-full text-left text-xs p-3 rounded-lg border border-zinc-200 hover:bg-zinc-50 hover:border-zinc-300 dark:border-zinc-700 dark:hover:bg-zinc-800 dark:hover:border-zinc-600"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, idx) => (
            <TurnView
              key={`turn-${idx}-${turn.timestamp}`}
              turn={turn}
              persona={persona}
            />
          ))}
        </div>

        {/* 入力フォーム */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
          className="space-y-3"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="例: 26歳、リモートワーク、子育て予定です。家賃 5000 万円以下、保育園充実な街は?"
            disabled={isLoading}
            rows={3}
            className={cn(
              "w-full rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm",
              "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
              "dark:border-zinc-700 dark:bg-zinc-800",
              isLoading && "opacity-50 cursor-not-allowed",
            )}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                handleSubmit();
              }
            }}
          />
          <div className="flex items-center justify-between">
            <div className="text-xs text-zinc-500">
              ⌘+Enter で送信 / 単発相談 (会話履歴は保存されません)
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleOpenHistory}
                disabled={isLoading || historyLoading}
                className="px-4 py-2 text-sm font-medium rounded-lg border border-zinc-300 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
              >
                📜 過去の相談履歴
              </button>
              {turns.length > 0 && (
                <button
                  type="button"
                  onClick={handleReset}
                  disabled={isLoading}
                  className="px-4 py-2 text-sm font-medium rounded-lg border border-zinc-300 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
                >
                  新しい相談を始める
                </button>
              )}
              <button
                type="submit"
                disabled={isLoading || !input.trim()}
                className="px-6 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? "考え中..." : "送信"}
              </button>
            </div>
          </div>
        </form>
      </div>

      {/* Plan L+LL: 過去の相談履歴 Modal */}
      {isHistoryOpen && (
        <HistoryModal
          items={historyItems}
          loading={historyLoading}
          error={historyError}
          onSelect={handleSelectHistoryItem}
          onClose={() => setIsHistoryOpen(false)}
        />
      )}
    </main>
  );
}

// ============================================================================
// 過去の相談履歴 Modal (Plan L+LL Phase 4)
// ============================================================================

function HistoryModal({
  items,
  loading,
  error,
  onSelect,
  onClose,
}: {
  items: ConciergeHistoryItem[];
  loading: boolean;
  error: string | null;
  onSelect: (item: ConciergeHistoryItem) => void;
  onClose: () => void;
}): React.ReactElement {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="過去の相談履歴"
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/50 px-4 py-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-900"
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3 dark:border-zinc-700">
          <h2 className="text-sm font-semibold">
            📜 過去の相談履歴 (最新 20 件)
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="閉じる"
            className="rounded-lg px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            ✕ 閉じる
          </button>
        </div>

        <div className="max-h-[calc(80vh-3rem)] overflow-y-auto p-4 space-y-2">
          {loading && (
            <div className="py-8 text-center text-sm text-zinc-500">
              ⏳ 履歴を取得中...
            </div>
          )}
          {!loading && error && (
            <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
              ❌ {error}
              <div className="mt-1 text-rose-600 dark:text-rose-400">
                Firestore に履歴が未登録の場合や認可エラーの場合があります
              </div>
            </div>
          )}
          {!loading && !error && items.length === 0 && (
            <div className="py-8 text-center text-sm text-zinc-500">
              💭 まだ Concierge に相談したことがありません
              <div className="mt-1 text-xs">
                相談すると、次回からここに過去の対話が並びます
              </div>
            </div>
          )}
          {!loading &&
            !error &&
            items.map((item) => (
              <button
                key={item.doc_id}
                type="button"
                onClick={() => onSelect(item)}
                className="block w-full text-left rounded-lg border border-zinc-200 bg-white p-3 transition hover:border-blue-400 hover:bg-blue-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-blue-600 dark:hover:bg-zinc-800"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-xs text-zinc-500">
                    {item.timestamp
                      ? new Date(item.timestamp).toLocaleString("ja-JP", {
                          year: "numeric",
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "-"}
                  </div>
                  {item.matched_interests.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {item.matched_interests.map((i) => (
                        <span
                          key={i}
                          className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                        >
                          {i}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="mt-2 line-clamp-2 text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {item.message}
                </div>
                {item.short_summary && (
                  <div className="mt-1 line-clamp-2 text-xs text-zinc-600 dark:text-zinc-400">
                    → {item.short_summary}
                  </div>
                )}
                {item.candidates_codes.length > 0 && (
                  <div className="mt-1 text-[10px] text-zinc-500">
                    候補 {item.candidates_codes.length} 件:{" "}
                    {item.candidates_codes.slice(0, 3).join(", ")}
                    {item.candidates_codes.length > 3 ? " ..." : ""}
                  </div>
                )}
                <div className="mt-2 text-[10px] text-blue-600 dark:text-blue-400">
                  ↺ このメッセージを再入力する
                </div>
              </button>
            ))}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 1 ターン分の表示
// ============================================================================

function TurnView({
  turn,
  persona,
}: {
  turn: ChatTurn;
  persona: Persona | null;
}): React.ReactElement {
  if (turn.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-blue-600 text-white px-4 py-3 text-sm whitespace-pre-wrap">
          {turn.message}
        </div>
      </div>
    );
  }
  if (turn.kind === "loading") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[80%] rounded-2xl rounded-bl-sm bg-zinc-100 dark:bg-zinc-800 px-4 py-3 text-sm">
          <div className="flex items-center gap-2 text-zinc-500">
            <span className="animate-pulse">🤖</span>
            <span>Agent が tool を呼んで考え中... (5-20 秒)</span>
          </div>
        </div>
      </div>
    );
  }
  // agent turn
  const { response, durationMs } = turn;
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-full space-y-3">
        {/* Reply 本文 (Markdown レンダリング) */}
        <div className="rounded-2xl rounded-bl-sm bg-zinc-100 dark:bg-zinc-800 px-4 py-3 text-sm">
          <div className="markdown-body space-y-2">
            <ReactMarkdown
              components={{
                p: ({ children }) => (
                  <p className="leading-relaxed">{children}</p>
                ),
                h1: ({ children }) => (
                  <h1 className="text-base font-bold mt-3 mb-1">{children}</h1>
                ),
                h2: ({ children }) => (
                  <h2 className="text-sm font-bold mt-3 mb-1">{children}</h2>
                ),
                h3: ({ children }) => (
                  <h3 className="text-sm font-semibold mt-3 mb-1">
                    {children}
                  </h3>
                ),
                ul: ({ children }) => (
                  <ul className="list-disc pl-5 space-y-1">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="list-decimal pl-5 space-y-1">{children}</ol>
                ),
                li: ({ children }) => <li>{children}</li>,
                strong: ({ children }) => (
                  <strong className="font-semibold">{children}</strong>
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline hover:text-blue-800 dark:text-blue-400"
                  >
                    {children}
                  </a>
                ),
                code: ({ children }) => (
                  <code className="rounded bg-zinc-200 px-1 py-0.5 text-xs dark:bg-zinc-700">
                    {children}
                  </code>
                ),
              }}
            >
              {response.reply}
            </ReactMarkdown>
          </div>
        </div>

        {/* 候補 card (search_municipalities が呼ばれた時のみ) */}
        {response.candidates.length > 0 && (
          <CandidateCards candidates={response.candidates} />
        )}

        {/* tool_calls 履歴 (折りたたみ、審査員向け演出) */}
        {response.tool_calls.length > 0 && (
          <ToolCallsView tools={response.tool_calls} totalMs={durationMs} />
        )}

        {/* 倫理 violation 警告 */}
        {response.ethical_violations.length > 0 &&
          response.ethical_violations[0] !== "client_error" && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
              ⚠️ 倫理ガード作動: {response.ethical_violations.join(", ")}
            </div>
          )}

        {/* Plan PP: Reasoning Transparency (Meta-Reasoner) — 倫理 OK の場合のみ表示 */}
        {response.ethical_violations.length === 0 && response.reply && (
          <div className="flex justify-end">
            <ReasoningExplainerButton
              agentName="concierge"
              rawReasoning={response.reply.slice(0, 500)}
              agentOutputSummary={`tool_calls=${response.tool_calls.length}, candidates=${response.candidates.length}${
                response.candidates.length > 0
                  ? ` (TOP: ${response.candidates[0].name})`
                  : ""
              }`}
              personaContext={
                persona
                  ? `${persona.age_group}${persona.interests.length > 0 ? " / 関心軸: " + persona.interests.join(",") : ""}`
                  : undefined
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// 自治体候補カード (search_municipalities の output 用)
// ============================================================================

function CandidateCards({
  candidates,
}: {
  candidates: MunicipalityCandidate[];
}): React.ReactElement {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {candidates.slice(0, 5).map((c) => (
        <div
          key={c.municipality_code}
          className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-700 dark:bg-zinc-900"
        >
          <div className="flex items-baseline justify-between gap-2">
            <div className="font-semibold text-sm">{c.name}</div>
            <div className="text-xs text-zinc-500">{c.prefecture}</div>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <div className="text-xs">
              <span className="font-semibold">{c.match_score.toFixed(0)}</span>
              <span className="text-zinc-500">/100</span>
            </div>
            {c.matched_interests.length > 0 && (
              <div className="flex gap-1 text-xs text-zinc-500">
                {c.matched_interests.map((i) => (
                  <span
                    key={i}
                    className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                  >
                    {i}
                  </span>
                ))}
              </div>
            )}
          </div>
          {c.financial_capability_index != null && (
            <div className="mt-1 text-[11px] text-zinc-500">
              💰 財政力指数{" "}
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {c.financial_capability_index.toFixed(2)}
              </span>
              <span className="text-zinc-400">（1.0超で財政的余裕）</span>
            </div>
          )}
          <div className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
            {c.summary_text}
          </div>
          <Link
            href={`/cities/${c.municipality_code}`}
            className="mt-2 inline-block text-xs text-blue-600 underline hover:text-blue-700 dark:text-blue-400"
          >
            街ダッシュボードを見る →
          </Link>
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// Tool calls 履歴 (折りたたみ、ハッカソン審査員向け)
// ============================================================================

function ToolCallsView({
  tools,
  totalMs,
}: {
  tools: ToolCallLog[];
  totalMs: number;
}): React.ReactElement {
  return (
    <details className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs dark:border-zinc-700 dark:bg-zinc-900">
      <summary className="cursor-pointer font-semibold text-zinc-700 dark:text-zinc-300">
        🔧 Agent が呼んだ Tool 履歴 ({tools.length} 個 / 合計{" "}
        {(totalMs / 1000).toFixed(1)} 秒)
      </summary>
      <div className="mt-2 space-y-2">
        {tools.map((t, idx) => (
          <div
            key={`tool-${idx}-${t.name}`}
            className="rounded border border-zinc-200 bg-white p-2 dark:border-zinc-700 dark:bg-zinc-950"
          >
            <div className="flex items-baseline justify-between">
              <div className="font-mono text-zinc-700 dark:text-zinc-300">
                {t.name}()
              </div>
              <div className="text-zinc-500">{t.duration_ms} ms</div>
            </div>
            <details className="mt-1">
              <summary className="cursor-pointer text-zinc-500">
                引数 / 出力 preview
              </summary>
              <pre className="mt-1 overflow-x-auto bg-zinc-100 p-2 text-[10px] dark:bg-zinc-800">
                {JSON.stringify(t.args, null, 2)}
              </pre>
              <pre className="mt-1 overflow-x-auto bg-zinc-100 p-2 text-[10px] dark:bg-zinc-800">
                {t.output_preview}
              </pre>
            </details>
          </div>
        ))}
      </div>
    </details>
  );
}
