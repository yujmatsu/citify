import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { runWatcher } from "@/lib/api";

// 非同期 runWatcher (POST 202 → /analysis を新 run_id までポーリング) のロジック検証。
// global fetch を差し替え、fake timer でポーリング間隔を進める (TASK: web vitest)。

function jsonRes(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const runLog = (runId: string) => ({
  user_id: "u",
  run_id: runId,
  towns_checked: [],
  tool_calls: [],
  n_discoveries: 0,
  status: "ok",
  note: "",
});

const analysisResp = (runId: string | null) => ({
  user_id: "u",
  analysis: null,
  latest_run: runId ? runLog(runId) : null,
});

describe("runWatcher (非同期ポーリング)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("新しい run_id が現れるまで /analysis をポーリングして返す", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(analysisResp("old"))) // ① 直前 GET → prev=old
      .mockResolvedValueOnce(jsonRes({ status: "running" }, true, 202)) // ② POST 202
      .mockResolvedValueOnce(jsonRes(analysisResp("old"))) // ③ poll: まだ old
      .mockResolvedValueOnce(jsonRes(analysisResp("fresh"))); // ④ poll: 新 run_id
    vi.stubGlobal("fetch", fetchMock);

    const p = runWatcher("u");
    // 2 回分のポーリング間隔(各4s)をまとめて進める (timing に頑健)
    await vi.advanceTimersByTimeAsync(10_000);
    const res = await p;

    expect(res.run_log.run_id).toBe("fresh");
    // ①直前 + ②POST + ③④poll = 4 回
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("POST が失敗したら ApiError を投げる", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(analysisResp("old")))
      .mockResolvedValueOnce(jsonRes({ detail: "no watchlist" }, false, 400));
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWatcher("u")).rejects.toMatchObject({ status: 400 });
  });
});
