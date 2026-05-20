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

# uv で高速インストール (deterministic, 並列、cache 効率)
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# 依存関係のみ先にインストール (レイヤキャッシュ最大化)
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    uv pip install --no-cache fastapi uvicorn[standard] httpx pydantic pydantic-settings \
                              google-cloud-logging google-cloud-secret-manager structlog

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

USER citify

# Cloud Run は PORT 環境変数を注入 (default 8080)
ENV PORT=8080
EXPOSE 8080

# Production 起動: uvicorn (workers=1, Cloud Run は instance level で scaling)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
