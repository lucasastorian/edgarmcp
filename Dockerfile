FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[railway]"

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/edgarmcp /usr/local/bin/edgarmcp
COPY src/ src/

ENV PORT=8000
EXPOSE ${PORT}

# Citations work remotely — set EDGARMCP_BASE_URL to your deployment URL
# (e.g. https://edgarmcp-production.up.railway.app) for clickable citation links.
# Auth is auto-generated when binding to 0.0.0.0; set EDGARMCP_API_KEY to override.
CMD python -m edgarmcp --http --host 0.0.0.0 --port ${PORT:-8000}
