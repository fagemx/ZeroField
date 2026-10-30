#!/usr/bin/env bash
# Container entry: seed, serve the studio on loopback in header mode, put nginx in front on 7860.
set -euo pipefail
cd /app

GUEST=99999999-9999-4999-8999-999999999999
SECRET=$(python -c 'import secrets; print(secrets.token_hex(24))')

python deploy/hf-space/demo_seed.py "$GUEST"

export OPENBENCH_DB_URI="postgresql://postgres@127.0.0.1:${OPENBENCH_PG_PORT}/postgres"
export OPENBENCH_AUTH_MODE=header
export OPENBENCH_HEADER_SECRET="$SECRET"
sed -e "s/__SECRET__/$SECRET/" -e "s/__GUEST__/$GUEST/" deploy/hf-space/nginx.conf > /tmp/nginx.conf

python run_studio.py --host 127.0.0.1 --port 3020 --no-worker &
python deploy/hf-space/demo_prime.py || echo "Priming failed: Story & World will ask the guest to initialize the writing workspace." >&2
nginx -c /tmp/nginx.conf -g 'daemon off;' &

# Either process exiting stops the container, so the Space restarts from a fresh seed.
wait -n
exit 1
