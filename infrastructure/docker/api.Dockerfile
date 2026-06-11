FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv

# deps first (cached layer) — only re-runs if manifests change
COPY pyproject.toml uv.lock ./
COPY packages/api/pyproject.toml ./packages/api/
RUN uv sync --frozen --no-dev --package solus-api

# code second — changes here don't bust the deps layer
COPY packages/api/src ./packages/api/src

EXPOSE 8000
CMD ["uv", "run", "--package", "solus-api", "uvicorn", "solus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]