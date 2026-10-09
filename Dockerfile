FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv pip install --system --no-cache ".[server]"

RUN useradd --uid 1000 --create-home emusync && mkdir /data && chown emusync /data
USER emusync

ENV EMUSYNC_DATA=/data
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["emusync", "serve", "--host", "0.0.0.0", "--port", "8080"]
