"""ADK Runner viability spike (TASK-WATCHER Slice 1)。

目的: google-adk 2.1.0 の Runner が現環境で「LLM が自分でツールを選ぶ自律ループ」を
回せるかを最小構成で検証する。通れば watcher を ADK Runner で実装(理想形)、
ダメなら genai 反復 function-calling にフォールバック。

使い方 (Gemini キー + 読める google.genai が要るので人間の実環境で実行):
    cd ~/projects/citify
    set -a; source .env; set +a   # GOOGLE_CLOUD_PROJECT / Vertex 認証
    apps/api/.venv/bin/python -m scrapers.reinfolib.adk_runner_spike

期待: ツール 'get_population' を LLM が自分で呼び、最終応答に人口を含む。
      末尾に SPIKE_RESULT=OK が出れば ADK Runner 採用可。
"""

from __future__ import annotations

import asyncio
import os
import sys


# --- ダミーツール (LLM が自分で呼ぶかを見る) ---
def get_population(municipality: str) -> dict:
    """指定した市区町村の人口を返す。

    Args:
        municipality: 市区町村名 (例: 朝霞市)
    """
    table = {"朝霞市": 141083, "新宿区": 349385, "高知市": 321543}
    return {"municipality": municipality, "population": table.get(municipality, -1)}


async def _main() -> int:
    proj = os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev")
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

    try:
        from google.adk import Agent, Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools import FunctionTool
        from google.genai import types as gat
    except Exception as exc:  # noqa: BLE001
        print(f"IMPORT_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("SPIKE_RESULT=IMPORT_FAILED")
        return 1

    agent = Agent(
        name="spike_agent",
        model="gemini-2.5-flash",
        instruction=(
            "あなたは人口アシスタント。ユーザーが街の人口を尋ねたら、必ず get_population "
            "ツールを使って正確な数値を取得し、日本語で簡潔に答えてください。"
        ),
        tools=[FunctionTool(func=get_population)],
    )

    session_service = InMemorySessionService()
    app_name, user_id, session_id = "spike", "u1", "s1"
    await session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)

    msg = gat.Content(role="user", parts=[gat.Part(text="朝霞市の人口は?")])
    tool_called = False
    final_text = ""
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=msg
        ):
            # function_call が出れば「LLM が自分でツールを選んだ」証跡
            for part in getattr(getattr(event, "content", None), "parts", []) or []:
                if getattr(part, "function_call", None):
                    tool_called = True
                    print(f"  TOOL_CALL: {part.function_call.name}({dict(part.function_call.args)})")
            if getattr(event, "is_final_response", lambda: False)():
                final_text = (event.content.parts[0].text or "") if event.content else ""
    except Exception as exc:  # noqa: BLE001
        print(f"RUN_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("SPIKE_RESULT=RUN_FAILED")
        return 1

    print(f"  final_text: {final_text[:120]}")
    ok = tool_called and "141083" in final_text.replace(",", "")
    print(f"  tool_called={tool_called} project={proj}")
    print(f"SPIKE_RESULT={'OK' if ok else 'PARTIAL(動くがツール未使用 or 数値不一致)'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
