# ── build stage ──
FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml .
RUN pip install --upgrade pip && pip install --no-cache-dir build && python -m build --wheel

# ── runtime stage ──
FROM python:3.11-slim AS runtime
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl uvicorn[standard] && rm /tmp/*.whl

COPY src/sports_arb/infrastructure/web/static /app/static

USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "sports_arb.infrastructure.web.server:app", "--host", "0.0.0.0", "--port", "8000"]
