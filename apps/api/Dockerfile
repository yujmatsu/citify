# Citify API — Cloud Run 用 Docker イメージ
# Multi-stage build で本番イメージサイズを最小化 (~150 MB)
#
# Build:
#   docker build -t citify-api:dev -f apps/api/Dockerfile apps/api
# Run (ローカル):
#   docker run -p 8080:8080 -e PORT=8080 citify-api:dev

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
COPY pyproject.toml ./
RUN uv pip install --no-cache \
    fastapi uvicorn[standard] httpx pydantic pydantic-settings \
    google-cloud-logging google-cloud-secret-manager google-cloud-bigquery \
    google-cloud-aiplatform google-cloud-firestore \
    structlog

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

# アプリコード
COPY --chown=citify:citify main.py ./
COPY --chown=citify:citify rag ./rag

USER citify

# Cloud Run は PORT 環境変数を注入 (default 8080)
ENV PORT=8080
EXPOSE 8080

# Production 起動: uvicorn (workers=1, Cloud Run は instance level で scaling)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
