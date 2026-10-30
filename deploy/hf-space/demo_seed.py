"""Seed the Updraft showcase the way a development launch does, then add the demo guest.

The guest is a crew member ("member"), not a viewer, so the studio renders its full composer; nginx.conf is what
keeps the demo read-only.

Runs once per container start, before the studio is served in header mode (which never seeds).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.pop("OPENBENCH_AUTH_MODE", None)

import run_studio  # noqa: E402
import server  # noqa: E402
from project_docs import http, repository as repo  # noqa: E402


def main(guest_id):
    uri, _ = server._start_local_postgres()  # pg_ctl leaves the cluster running for the studio
    os.environ["OPENBENCH_DB_URI"] = uri
    conn = http.open_connection()
    try:
        server.seed_demo_data(conn)
        run_studio.seed_showcase_media(conn)
        run_studio.seed_showcase_previs(conn)
        repo.upsert_member(conn, guest_id, "Demo guest", "member", "guest@zerofield.example", "active")
        conn.commit()
    finally:
        conn.close()
    print(f"Seeded the showcase; guest {guest_id} on {uri}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
