FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-local-model" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="0.1.0"
RUN addgroup -g 1000 wizard && adduser -D -u 1000 -G wizard wizard \
    && mkdir -p /data/private /models && chown -R 1000:1000 /data /models
WORKDIR /app
COPY app app
COPY web web
COPY openapi.json LICENSE ./
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data/private MODEL_DIR=/models
EXPOSE 18805 8090
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:18805/healthz',timeout=3).read()"
CMD ["python", "app/server.py"]
