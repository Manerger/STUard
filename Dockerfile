# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.14-slim

# ---------------------------------------------------------------- build
FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential pkg-config libxml2-dev libxslt1-dev zlib1g-dev libxmlsec1-dev libxmlsec1-openssl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
# lxml and xmlsec are built against the same system libxml2, otherwise xmlsec refuses to load
# ("lxml & xmlsec libxml2 library version mismatch").
RUN pip wheel --no-binary lxml,xmlsec --wheel-dir /wheels .

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxmlsec1-openssl libxslt1.1 tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /wheels
RUN pip install --no-index /wheels/*.whl \
 && rm -rf /wheels \
 && python -c "import lxml.etree, xmlsec, onelogin.saml2.auth, stuard.bot.app"

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin stuard \
 && mkdir -p /app /data \
 && chown stuard:stuard /data
WORKDIR /app
USER stuard

ENV DATABASE_PATH=/data/stuard.sqlite3 \
    CONFIG_PATH=/app/config.yaml \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "stuard"]
