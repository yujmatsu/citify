import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // monorepo 内に複数 lockfile があるため、apps/web 自身を root に固定
  // (上位 pnpm-lock.yaml を誤検出されないように)
  turbopack: {
    root: path.resolve(__dirname),
  },

  // Phase Q: 静的アセットの CDN/ブラウザキャッシュ最適化
  async headers() {
    return [
      {
        // 1,795 件 207KB の自治体マスタ。1 日固定で十分 (build 時に再生成可能)
        source: "/municipalities.json",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
