import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// web ユニットテスト (TASK: web vitest)。@/ エイリアスを解決し、node 環境でロジックを検証する
// (コンポーネント描画は対象外。zod スキーマ契約・runWatcher ポーリング・純関数が対象)。
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
