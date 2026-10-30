# Read-only public demo of the seeded Updraft production (Hugging Face Docker Space).
# Build from the repository root: docker build -f deploy/hf-space/Dockerfile -t zerofield-demo .
# Nothing here generates or changes: the studio runs with --no-worker, and nginx passes only reads and previews.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql nginx \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs the container as uid 1000.
RUN useradd -m -u 1000 user \
    && mkdir -p /var/run/postgresql \
    && chown user /var/run/postgresql

WORKDIR /app
COPY --chown=user . /app
# A Windows checkout may bring CRLF line endings; bash needs LF.
RUN sed -i 's/\r$//' /app/deploy/hf-space/start.sh \
    && pip install --no-cache-dir -e /app

USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    OPENBENCH_PG_BIN=/usr/lib/postgresql/15/bin \
    OPENBENCH_PG_DATA=/home/user/pgdata \
    OPENBENCH_PG_PORT=55432

EXPOSE 7860
CMD ["bash", "/app/deploy/hf-space/start.sh"]
