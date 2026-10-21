# CPU baseline is deliberate. A GPU wheel/image is a separate benchmarked change.
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" OCR_DEVICE=cpu PADDLE_PDX_CACHE_HOME=/opt/models PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra worker --no-cache
COPY backend ./backend
COPY worker ./worker
# Download the exact configured detector/Latin recognizer during build, not a paid cold start.
RUN python -c "from worker.pipeline import paddle_engine; paddle_engine()"
RUN useradd --create-home appuser && chown -R appuser:appuser /opt/models /app
USER appuser
CMD ["python", "-u", "-m", "worker.handler"]
