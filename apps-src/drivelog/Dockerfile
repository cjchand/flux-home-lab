FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install only the dependencies declared in pyproject.toml (cached layer).
COPY pyproject.toml ./
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))
PY
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy the full package as-is so templates/, static/ and sql/ are present.
COPY drivelog ./drivelog

RUN useradd --system --uid 10001 --no-create-home drivelog
USER drivelog

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "drivelog.app:app", "--host", "0.0.0.0", "--port", "8080"]
