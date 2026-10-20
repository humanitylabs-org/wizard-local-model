# llama.cpp b11749: pinned multiarchitecture upstream, retained binaries and licenses.
FROM ghcr.io/ggml-org/llama.cpp:server@sha256:9fbaa06d7f4449e2ae0d02b40e0431f7c212dcf231c9e3a7777a6afc2cc8f312
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-local-model" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="0.1.0"
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/private /models && chown -R 1000:1000 /data /models
WORKDIR /app
COPY app app
COPY web web
COPY openapi.json LICENSE ./
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data/private MODEL_DIR=/models
EXPOSE 18805 8090
HEALTHCHECK --interval=10s --timeout=5s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:18805/healthz',timeout=3).read()"
ENTRYPOINT ["python3"]
CMD ["app/launch.py"]
