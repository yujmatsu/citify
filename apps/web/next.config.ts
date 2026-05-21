import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // monorepo 内に複数 lockfile があるため、apps/web 自身を root に固定
  // (上位 pnpm-lock.yaml を誤検出されないように)
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
