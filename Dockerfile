FROM node:22-bookworm-slim AS ui
WORKDIR /build/ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBENCH_RUNTIME_ROOT=/home/openbench/.openbench_runtime
WORKDIR /app
COPY pyproject.toml setup.py MANIFEST.in README.md LICENSE server.py ./
COPY project_docs/ project_docs/
COPY project_assistant/ project_assistant/
COPY openbench_data/ openbench_data/
COPY db/ db/
COPY --from=ui /build/static/projects/ static/projects/
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 openbench
USER openbench
EXPOSE 3020
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3020/healthz',timeout=2)"
CMD ["openbench", "--host", "0.0.0.0", "--port", "3020"]
