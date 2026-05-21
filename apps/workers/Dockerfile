# Citify Workers — Cloud Run Job 用 Docker イメージ
#
# 1 つの image に 4 つの worker (translator / relevance / distributor / bq_sink)
# を同梱、Cloud Run Job 側で CMD オーバーライドして種別を切り替える。
#
# Build:
#   docker build -t citify-worker:dev -f apps/workers/Dockerfile .
# Run (ローカル):
#   docker run --rm -v ~/.config/gcloud:/root/.config/gcloud \
#     citify-worker:dev \
#     python -m agents.translator.worker --project-id citify-dev --timeout-sec 30
#
# Build (Cloud Build):
#   gcloud builds submit --config=cloudbuild-workers.yaml --region=asia-northeast1

# ============================================================================
# Stage 1: builder — 依存パッケージのインストール
# ============================================================================
FROM python:3.12-slim AS builder

# uv で高速インストール
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /build

# venv 作成
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 依存関係インストール (apps/api/pyproject.toml の依存をフラットに展開)
# Worker は scrapers/kaigiroku は使わない (Playwright 不要) ので軽量版
RUN uv pip install --no-cache \
    httpx \
    pydantic pydantic-settings \
    google-cloud-logging google-cloud-secret-manager \
    google-cloud-bigquery google-cloud-storage \
    google-cloud-aiplatform google-cloud-pubsub \
    google-genai \
    structlog \
    feedparser \
    beautifulsoup4 lxml

# ============================================================================
# Stage 2: runtime — 最小ランタイム
# ============================================================================
FROM python:3.12-slim AS runtime

# 非 root ユーザー (セキュリティ)
RUN groupadd -r citify && useradd -r -g citify -d /app -s /sbin/nologin citify

WORKDIR /app

# venv コピー
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# プロジェクトコード (worker が import する範囲のみ)
COPY --chown=citify:citify pkg /app/pkg
COPY --chown=citify:citify agents /app/agents
COPY --chown=citify:citify scrapers /app/scrapers

USER citify

# Cloud Run Job では CMD を実行時オーバーライドする (Terraform で指定)
# デフォルトは使用方法を出力して exit
CMD ["python", "-c", "import sys; print('Override CMD to one of: agents.translator.worker / agents.relevance.worker / agents.distributor.worker / pkg.bq_sink_runner', file=sys.stderr); sys.exit(1)"]
