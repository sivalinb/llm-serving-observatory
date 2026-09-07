FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml requirements.lock ./
COPY observatory ./observatory
RUN pip install -r requirements.lock && pip install --no-deps . && useradd --uid 10001 --create-home lab && mkdir -p /app/data && chown lab:lab /app/data
USER lab
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "observatory.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
