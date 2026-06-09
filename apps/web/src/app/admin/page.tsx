import Link from "next/link";

/**
 * 開発者向けインデックス。
 * Scraper/Cost Health は運用・監視用のため一般導線(ホーム)から外し、ここに隔離する。
 */
export default function AdminIndexPage(): React.JSX.Element {
  return (
    <main className="mx-auto flex max-w-md flex-1 flex-col gap-5 px-6 py-10">
      <Link
        href="/"
        className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"
      >
        ← ホーム
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-bold">開発者向け</h1>
        <p className="text-sm text-zinc-500">
          運用・監視ダッシュボード（一般ユーザー向けではありません）。
        </p>
      </div>
      <div className="space-y-3">
        <Link
          href="/admin/scrapers"
          className="block rounded-2xl border border-zinc-300 p-4 transition-colors hover:border-emerald-400 dark:border-zinc-700 dark:hover:border-emerald-700"
        >
          <div className="font-semibold">🩺 Scraper Health</div>
          <p className="mt-0.5 text-xs text-zinc-500">
            スクレイパーの稼働状況・robots 判定・取得鮮度
          </p>
        </Link>
        <Link
          href="/admin/costs"
          className="block rounded-2xl border border-zinc-300 p-4 transition-colors hover:border-emerald-400 dark:border-zinc-700 dark:hover:border-emerald-700"
        >
          <div className="font-semibold">💸 Cost Health</div>
          <p className="mt-0.5 text-xs text-zinc-500">
            API/LLM コストの推移・異常検知
          </p>
        </Link>
      </div>
    </main>
  );
}
