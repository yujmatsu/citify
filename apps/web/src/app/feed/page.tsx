"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { FeedCard } from "@/components/feed-card";
import { fetchFeed, type FeedItem } from "@/lib/api";
import { getLastSeen, isNewerThan, setLastSeen } from "@/lib/last-seen";
import { DEMO_PERSONA, loadPersona, type Persona } from "@/lib/persona";
import { RECOMMENDED_MUNICIPALITIES } from "@/lib/recommended";
import { cn } from "@/lib/utils";

/** 「前回訪問以降の変化」リテンションフック (criterion ④) 用の localStorage key。 */
const FEED_LAST_SEEN_KEY = "feed";

type FeedScope = "my_city" | "national";

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; items: FeedItem[]; persona: Persona }
  | { kind: "empty"; persona: Persona }
  | { kind: "error"; message: string; persona: Persona };

export default function FeedPage() {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [scope, setScope] = useState<FeedScope>("my_city");
  // 「前回訪問以降の変化」: 今回の訪問で上書きする前の lastSeen を保持 (新着判定の基準)
  const [lastSeen, setLastSeenState] = useState<string | null>(null);
  const [newBannerDismissed, setNewBannerDismissed] = useState(false);
  const lastSeenSavedRef = useRef(false);

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      router.replace("/onboarding");
      return;
    }
    // 新着判定の基準にするため、上書き前の lastSeen を先に読んでおく
    setLastSeenState(getLastSeen(FEED_LAST_SEEN_KEY));
    let cancelled = false;
    fetchFeed(persona.user_id, { limit: 50 })
      .then((res) => {
        if (cancelled) return;
        if (res.items.length === 0) {
          setState({ kind: "empty", persona });
        } else {
          setState({ kind: "ok", items: res.items, persona });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
          persona,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  // フィードが正常に描画された後、今回の訪問時刻を「最後に見た時刻」として保存する。
  // lastSeen state は既に読み込み済みなので、今回のレンダーの新着判定には影響しない。
  useEffect(() => {
    if (state.kind === "ok" && !lastSeenSavedRef.current) {
      lastSeenSavedRef.current = true;
      setLastSeen(FEED_LAST_SEEN_KEY, new Date().toISOString());
    }
  }, [state.kind]);

  // マイ街 / 全国 スコープでフィルタリング
  const { displayItems, myCityCount, nationalCount } = useMemo(() => {
    if (state.kind !== "ok") {
      return { displayItems: [], myCityCount: 0, nationalCount: 0 };
    }
    const myCityCodes = new Set(state.persona.municipality_codes);
    const myCity: FeedItem[] = [];
    const national: FeedItem[] = [];
    for (const item of state.items) {
      const code = item.municipality_code ?? "";
      // 「マイ街」: ユーザー登録自治体 (00000 国会も含む) と一致
      // 「全国」: それ以外 = 自分の街にないが採点されたもの
      if (myCityCodes.has(code)) {
        myCity.push(item);
      } else {
        national.push(item);
      }
    }
    return {
      displayItems: scope === "my_city" ? myCity : national,
      myCityCount: myCity.length,
      nationalCount: national.length,
    };
  }, [state, scope]);

  // 「前回訪問以降の変化」: 表示中タブの中で前回訪問より新しい件数 (再訪問のきっかけ)
  const newCount = useMemo(
    () =>
      displayItems.filter((item) => isNewerThan(item.meeting_date, lastSeen))
        .length,
    [displayItems, lastSeen],
  );

  // キーボード操作 (ArrowDown/ArrowUp/j/k) でカード間をスナップスクロールするための ref
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<(HTMLElement | null)[]>([]);

  const scrollToCardIndex = (index: number) => {
    const total = displayItems.length;
    if (total === 0) return;
    const clamped = Math.max(0, Math.min(index, total - 1));
    cardRefs.current[clamped]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  // 現在ビューポート上端に最も近いカードの index を探す (キー操作の基準位置)
  const findCurrentCardIndex = (): number => {
    const container = scrollContainerRef.current;
    if (!container) return 0;
    const containerTop = container.getBoundingClientRect().top;
    let closestIndex = 0;
    let closestDist = Number.POSITIVE_INFINITY;
    for (let i = 0; i < displayItems.length; i++) {
      const el = cardRefs.current[i];
      if (!el) continue;
      const dist = Math.abs(el.getBoundingClientRect().top - containerTop);
      if (dist < closestDist) {
        closestDist = dist;
        closestIndex = i;
      }
    }
    return closestIndex;
  };

  const handleFeedKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowDown" || event.key === "j") {
      event.preventDefault();
      scrollToCardIndex(findCurrentCardIndex() + 1);
    } else if (event.key === "ArrowUp" || event.key === "k") {
      event.preventDefault();
      scrollToCardIndex(findCurrentCardIndex() - 1);
    }
  };

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">フィードを読み込み中...</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">
            フィードの取得に失敗しました
          </h1>
          <p className="text-sm text-zinc-500">{state.message}</p>
          <p className="text-xs text-zinc-400">
            user_id: {state.persona.user_id} · API_BASE:{" "}
            {process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080"}
          </p>
          <Link
            href="/"
            className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            トップに戻る
          </Link>
        </div>
      </main>
    );
  }

  if (state.kind === "empty") {
    const isDemo = state.persona.user_id === DEMO_PERSONA.user_id;
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">まだ議題が届いていません</h1>
          <p className="text-sm text-zinc-500">
            user_id: <span className="font-mono">{state.persona.user_id}</span>
            {isDemo
              ? " — デモ用ペルソナですが、まだスコア対象が無いようです。"
              : " — このペルソナでは未だ採点された議題がありません。"}
          </p>
          <p className="text-xs text-zinc-400">
            scrapers から publish → translator/relevance/bq_sink
            が処理すると、ここに表示されます。
          </p>
          <div className="flex justify-center gap-3 pt-2">
            <Link
              href="/municipalities"
              className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              マイ自治体を編集
            </Link>
            <Link
              href="/"
              className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              トップに戻る
            </Link>
          </div>
        </div>
      </main>
    );
  }

  // OK: For You feed (snap-scroll vertical) + マイ街/全国 タブ
  return (
    <main className="flex flex-1 flex-col">
      {/* Top tab bar (sticky) */}
      <div className="sticky top-0 z-10 border-b border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
        <div className="mx-auto flex max-w-md items-center justify-around">
          <TabButton
            active={scope === "my_city"}
            onClick={() => setScope("my_city")}
            label="あなたの街"
            count={myCityCount}
          />
          <TabButton
            active={scope === "national"}
            onClick={() => setScope("national")}
            label="その他"
            count={nationalCount}
          />
        </div>
      </div>

      <div
        ref={scrollContainerRef}
        role="feed"
        aria-label="議題フィード"
        tabIndex={0}
        onKeyDown={handleFeedKeyDown}
        className="flex-1 snap-y snap-mandatory overflow-y-auto"
        style={{ scrollbarWidth: "none" }}
      >
        <div className="mx-auto flex max-w-md flex-col gap-4 sm:py-4">
          {newCount > 0 && !newBannerDismissed && (
            <div className="mx-4 mt-3 flex items-center justify-between gap-3 rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
              <span>🔔 前回以降 {newCount} 件の新着</span>
              <button
                type="button"
                onClick={() => setNewBannerDismissed(true)}
                aria-label="新着通知を閉じる"
                className="rounded-full px-2 py-0.5 text-xs text-emerald-700 hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-900"
              >
                ✕
              </button>
            </div>
          )}
          {displayItems.length === 0 ? (
            <EmptyTabHint scope={scope} persona={state.persona} />
          ) : (
            displayItems.map((item, index) => (
              <FeedCard
                key={item.speech_id}
                item={item}
                posinset={index + 1}
                setsize={displayItems.length}
                isNew={isNewerThan(item.meeting_date, lastSeen)}
                cardRef={(el) => {
                  cardRefs.current[index] = el;
                }}
              />
            ))
          )}
          <footer className="snap-end px-6 py-12 text-center text-xs text-zinc-500">
            <p>
              {scope === "my_city" ? "あなたの街" : "その他"} は{" "}
              {displayItems.length} 件
            </p>
            <p className="mt-3 flex flex-wrap justify-center gap-4">
              <Link
                href="/compare"
                className="font-medium text-emerald-700 underline hover:text-emerald-900 dark:text-emerald-300 dark:hover:text-emerald-200"
              >
                🔀 自治体を比較する
              </Link>
              <Link
                href="/municipalities"
                className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
              >
                マイ自治体を編集
              </Link>
              <Link
                href="/onboarding"
                className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
              >
                年代・関心軸を変更
              </Link>
            </p>
          </footer>
        </div>
      </div>
    </main>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-1 items-center justify-center gap-2 border-b-2 px-4 py-3 text-sm transition-colors",
        active
          ? "border-emerald-500 font-semibold text-emerald-700 dark:text-emerald-300"
          : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200",
      )}
      aria-pressed={active}
    >
      <span>{label}</span>
      <span
        className={cn(
          "rounded-full px-2 py-0.5 text-[10px] font-medium tabular-nums",
          active
            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
            : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
        )}
      >
        {count}
      </span>
    </button>
  );
}

function EmptyTabHint({
  scope,
  persona,
}: {
  scope: FeedScope;
  persona: Persona;
}): React.JSX.Element {
  if (scope === "my_city") {
    return (
      <div className="mx-4 my-12 space-y-3 rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-center dark:border-zinc-800 dark:bg-zinc-900">
        <p className="text-sm font-medium">
          あなたの街にはまだ議題がありません
        </p>
        <p className="text-xs text-zinc-500">
          登録自治体: {persona.municipality_codes.join(" / ")}
        </p>
        <p className="text-xs text-zinc-400">
          別の街を登録するか、「その他」タブを見てみてください。
        </p>
        <p className="flex flex-wrap items-center justify-center gap-2 text-xs text-zinc-400">
          <span>例:</span>
          {RECOMMENDED_MUNICIPALITIES.map((m) => (
            <Link
              key={m.code}
              href={`/cities/${m.code}`}
              className="rounded-full border border-zinc-300 px-2 py-0.5 text-zinc-600 hover:bg-white dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              {m.name}
            </Link>
          ))}
        </p>
        <Link
          href="/municipalities"
          className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-xs font-medium hover:bg-white dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          マイ自治体を編集
        </Link>
      </div>
    );
  }
  return (
    <div className="mx-4 my-12 rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
      その他の自治体の議題はまだありません
    </div>
  );
}
