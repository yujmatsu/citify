# Citify API — Cloud Run 用 Docker イメージ
# Multi-stage build で本番イメージサイズを最小化 (~150-200 MB)
#
# Build (build context = repo root、agents/ と pkg/ を含めるため必須):
#   docker build -t citify-api:dev -f apps/api/Dockerfile .
# Run (ローカル):
#   docker run -p 8080:8080 -e PORT=8080 citify-api:dev
#
# NOTE: Plan E (Concierge Agent) 以降、apps/api/main.py が agents.concierge を
#       import するため、build context を apps/api から repo root に変更済。
#       cloudbuild.yaml も同じく context=. に変更必須。

# ============================================================================
# Stage 1: builder — 依存パッケージのインストール
# ============================================================================
FROM python:3.12-slim AS builder

# uv で高速インストール (deterministic, 並列)
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# venv 作成 + uv pip install のターゲット指定
# (VIRTUAL_ENV 環境変数で uv pip install の install 先を venv に固定)
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 依存関係インストール
# NOTE: BuildKit 専用の --mount=type=cache はレガシー builder (Cloud Build) で
#       失敗するため不使用。Cloud Run のビルドは毎回フレッシュなので cache なくても OK
# NOTE:
#   - google-cloud-bigquery は /v1/feed endpoint (BQ scored_speeches_latest 読み込み)
#   - google-cloud-aiplatform は /v1/speeches/{id}/related endpoint (Vertex AI RAG Engine)
#   - google-cloud-firestore は /v1/speeches/{id}/reaction endpoint (Phase X リアクション永続化)
#   - google-adk は Plan C で導入、Plan E (Concierge) で main.py から実 import
COPY apps/api/pyproject.toml ./
RUN uv pip install --no-cache \
    fastapi uvicorn[standard] httpx pydantic pydantic-settings \
    google-cloud-logging google-cloud-secret-manager google-cloud-bigquery \
    google-cloud-aiplatform google-cloud-firestore \
    structlog \
    "google-adk>=2.1,<3.0"

# ============================================================================
# Stage 2: runtime — 最小ランタイム
# ============================================================================
FROM python:3.12-slim AS runtime

# 非 root ユーザー (セキュリティ)
RUN groupadd -r citify && useradd -r -g citify -d /app -s /sbin/nologin citify

WORKDIR /app

# builder から venv のみコピー
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# アプリコード (build context = repo root のため、apps/api/ プレフィックスで指定)
COPY --chown=citify:citify apps/api/main.py ./
COPY --chown=citify:citify apps/api/rag ./rag

# Plan E: agents/ + pkg/ を含める (Concierge ADK Agent が agents.translator 等を import)
COPY --chown=citify:citify agents ./agents
COPY --chown=citify:citify pkg ./pkg

USER citify

# Cloud Run は PORT 環境変数を注入 (default 8080)
ENV PORT=8080
EXPOSE 8080

# Production 起動: uvicorn (workers=1, Cloud Run は instance level で scaling)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
