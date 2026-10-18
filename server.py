"""ZeroField Studio server (HTTP Workbench + Background Agent Worker).

Usage:
    python server.py --embedded-db --port 3020
    OPENBENCH_DB_URI=postgresql://... python server.py --port 3020
"""
from __future__ import annotations

import argparse
import html
import http.cookies
import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from project_assistant import store as assistant_store
from project_assistant import worker as assistant_worker
from project_docs import auth, doc_schema, http as projects_http, markdown_import, repository as repo

DEMO_MEMBERS = [
    {
        "actor_id": "11111111-1111-4111-8111-111111111111",
        "name": "Alex Rivera",
        "role": "admin",
        "email": "alex@zerofield.example",
    },
    {
        "actor_id": "22222222-2222-4222-8222-222222222222",
        "name": "Maya Chen",
        "role": "director",
        "email": "maya@zerofield.example",
    },
    {
        "actor_id": "33333333-3333-4333-8333-333333333333",
        "name": "Sam Reed",
        "role": "engineer",
        "email": "sam@zerofield.example",
    },
]

def seed_demo_data(conn) -> None:
    """Create an editable English planning example without fabricated renders."""
    repo.ensure_schema(conn)
    for member in DEMO_MEMBERS:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM projectops.member WHERE actor_id=%s", (member["actor_id"],))
            exists = cur.fetchone()
        if not exists:
            repo.upsert_member(conn, member["actor_id"], member["name"], member["role"], member["email"], "active")
    slug = "zerofield-showcase"
    admin_id = DEMO_MEMBERS[0]["actor_id"]
    if not repo.get_project(conn, slug):
        from project_docs import service
        me = service.Identity(admin_id, DEMO_MEMBERS[0]["name"], "admin")
        code, result = service.create_project(conn, me, {
            "slug": slug, "title": "The Last Signal — ZeroField Studio",
            "template": "zerofield_studio", "status": "planning",
            "summary": "An editable production brief, cast lookbook, shot slate, V2V plan, and pipeline. Media generation is not configured.",
        })
        if code != 200:
            raise RuntimeError(result.get("error", "Could not create the studio example"))
        for member in DEMO_MEMBERS:
            assistant_store.set_member_enabled(conn, slug, member["actor_id"], True, admin_id)
    conn.commit()


class OpenBenchHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can silently share a port with an older process.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        import socket
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class OpenBenchHandler(BaseHTTPRequestHandler):
    default_actor_id = DEMO_MEMBERS[0]["actor_id"]

    def _cookie_actor(self) -> str | None:
        raw = self.headers.get("Cookie") or ""
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http.cookies.CookieError:
            return None
        morsel = jar.get("openbench_actor")
        return morsel.value if morsel else None

    def project_docs_identity(self, record_login: bool = False):
        cfg = auth.config()
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            pass
        actor_id = auth.resolve(self.headers, {k: v.value for k, v in jar.items()}, cfg, self.default_actor_id)
        if not actor_id:
            return None, "login"
        conn = projects_http.open_connection()
        try:
            members = repo.active_members(conn)
        finally:
            conn.close()
        hit = next((m for m in members if m["actor_id"] == actor_id), None)
        if not hit:
            return None, "membership"
        return {
            "actor_id": hit["actor_id"],
            "name": hit["name"],
            "role": hit["role"],
            "email": hit["email"],
            "status": "active",
            "directory_registered": True,
        }, None

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def send_json(self, status: int, payload: dict) -> None:
        if status >= 400:
            from project_docs.locale import error_details
            payload = error_details(payload)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_skillops_bytes(status, "application/json; charset=utf-8", data, cache_control="no-store")

    def send_skillops_bytes(self, status: int, content_type: str, data: bytes, *,
                            cache_control: str = "no-store", etag: str | None = None,
                            disposition: str | None = None, extra_headers: dict | None = None) -> None:
        total, content_range = len(data), None
        if status == 200 and content_type.startswith(("audio/", "video/")) and self.headers.get("Range"):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers["Range"])
            if match and any(match.groups()):
                start = int(match[1]) if match[1] else max(0, total - int(match[2]))
                end = min(total - 1, int(match[2])) if match[1] and match[2] else total - 1
                if 0 <= start <= end < total:
                    data, status, content_range = data[start:end + 1], 206, f"bytes {start}-{end}/{total}"
                else:
                    data, status, content_range = b"", 416, f"bytes */{total}"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type.startswith(("audio/", "video/")):
            self.send_header("Accept-Ranges", "bytes")
        if content_range:
            self.send_header("Content-Range", content_range)
        if etag:
            self.send_header("ETag", etag)
        if disposition:
            self.send_header("Content-Disposition", disposition)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _handle_who(self, parsed) -> None:
        if auth.config()["mode"] != "dev":
            self.send_json(404, {"error": "Not found"})
            return
        qs = parse_qs(parsed.query)
        actor = (qs.get("actor") or [self.default_actor_id])[0]
        next_url = (qs.get("next") or ["/projects/"])[0]
        if not next_url.startswith("/") or next_url.startswith("//") or "\\" in next_url or any(ord(c) < 32 for c in next_url):
            next_url = "/projects/"
        self.send_response(302)
        self.send_header("Set-Cookie", f"openbench_actor={actor}; Path=/; SameSite=Lax")
        self.send_header("Location", next_url)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._login_page()
            return
        if parsed.path == "/projects/api/auth":
            self.send_json(200, {"mode": auth.config()["mode"]})
            return
        if parsed.path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        if parsed.path == "/":
            self.send_response(302)
            self.send_header("Location", "/projects/")
            self.end_headers()
            return
        if parsed.path == "/__who":
            self._handle_who(parsed)
            return
        if projects_http.handle_projects(self, parsed, "GET"):
            return
        self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/login", "/logout"):
            self._login(parsed.path == "/logout")
            return
        if projects_http.handle_projects(self, parsed, "POST"):
            return
        self.send_json(404, {"error": "Not found"})

    def _login_page(self, error=""):
        from project_docs.locale import request_locale, login_html, preference_headers
        locale = request_locale(self)
        page = login_html(auth.config()["mode"], locale, error)
        self.send_skillops_bytes(200, "text/html; charset=utf-8", page.encode("utf-8"),
                                extra_headers=preference_headers(locale))

    def _login(self, logout=False):
        cfg = auth.config()
        if cfg["mode"] != "token":
            self.send_json(404, {"error": "Not found"})
            return
        origin = self.headers.get("Origin", "")
        if origin and origin not in ("http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")):
            self.send_json(403, {"error": "Cross-origin sign-in is not allowed."})
            return
        if logout and projects_http._write_allowed(self):
            self.send_json(403, {"error": "A required request header is missing."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= 8192:
                raise ValueError()
            data = parse_qs(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "Invalid sign-in request."})
            return
        actor = None if logout else auth.token_actor((data.get("token") or [""])[0], cfg)
        if not logout and actor:
            conn = projects_http.open_connection()
            try:
                actor = actor if any(m["actor_id"] == actor for m in repo.active_members(conn)) else None
            finally:
                conn.close()
        if not logout and not actor:
            self._login_page("Invalid token or disabled account.")
            return
        cookie = "" if logout else auth.issue_session(actor, cfg)
        secure = "; Secure" if os.environ.get("OPENBENCH_COOKIE_SECURE") == "1" else ""
        self.send_response(303)
        self.send_header("Set-Cookie", f"openbench_session={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if logout else auth.SESSION_SECONDS}{secure}")
        self.send_header("Location", "/login" if logout else "/projects/")
        self.send_header("Content-Length", "0")
        self.end_headers()


def _find_pg_bin() -> Path | None:
    import shutil
    configured = os.environ.get("OPENBENCH_PG_BIN")
    if configured:
        return Path(configured)
    found = shutil.which("pg_ctl")
    if found:
        return Path(found).parent
    for candidate in (
        Path(r"C:\Program Files\PostgreSQL\17\bin"),
        Path(r"C:\Program Files\PostgreSQL\16\bin"),
        Path(r"C:\Program Files\PostgreSQL\15\bin"),
    ):
        if (candidate / "pg_ctl.exe").exists() or (candidate / "pg_ctl").exists():
            return candidate
    try:
        import pgserver
        bundled = Path(pgserver.__file__).parent / "pginstall" / "bin"
        if (bundled / "pg_ctl.exe").exists() or (bundled / "pg_ctl").exists():
            return bundled
    except ImportError:
        pass
    return None


def _start_local_postgres() -> tuple[str, object]:
    import subprocess
    pg_bin = _find_pg_bin()
    if pg_bin is None:
        import pgserver
        db_dir = Path(tempfile.gettempdir()) / "openbench-pgdata"
        srv = pgserver.get_server(str(db_dir))
        return srv.get_uri(), srv.cleanup

    data_dir = Path(os.environ.get("OPENBENCH_PG_DATA") or Path(__file__).resolve().parent / ".openbench_pg")
    port = int(os.environ.get("OPENBENCH_PG_PORT", "55432"))
    initdb = str(pg_bin / ("initdb.exe" if os.name == "nt" else "initdb"))
    pg_ctl = str(pg_bin / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl"))
    if not (data_dir / "PG_VERSION").exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [initdb, "-D", str(data_dir), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    log_file = data_dir / "postgres.log"
    status = subprocess.run([pg_ctl, "-D", str(data_dir), "status"], capture_output=True)
    if status.returncode != 0:
        subprocess.run(
            [pg_ctl, "-D", str(data_dir), "-l", str(log_file), "-o", f"-p {port} -h 127.0.0.1", "start"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    uri = f"postgresql://postgres@127.0.0.1:{port}/postgres"
    return uri, lambda: subprocess.run([pg_ctl, "-D", str(data_dir), "stop"], capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="ZeroField Studio server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3020)
    parser.add_argument("--embedded-db", action="store_true", help="Start an embedded PostgreSQL development database")
    parser.add_argument("--no-worker", action="store_true", help="Disable the built-in background agent worker")
    args = parser.parse_args()
    try:
        cfg = auth.config()
    except auth.AuthError as exc:
        parser.error(str(exc))
    if cfg["mode"] == "dev" and args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("dev mode binds to loopback only; configure token or header authentication to expose the server")

    cleanup_pg = None
    if args.embedded_db and not os.environ.get("OPENBENCH_DB_URI"):
        uri, cleanup_pg = _start_local_postgres()
        os.environ["OPENBENCH_DB_URI"] = uri
        print(f"zerofield: started local postgres at {uri}", flush=True)

    conn = projects_http.open_connection()
    try:
        if cfg["mode"] == "dev":
            seed_demo_data(conn)
        else:
            repo.ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM projectops.member")
                empty = cur.fetchone()[0] == 0
            if empty:
                actor = os.environ.get("OPENBENCH_ADMIN_ID") or next(iter(cfg["tokens"].values()), None)
                if not actor:
                    parser.error("First start in header mode requires OPENBENCH_ADMIN_ID")
                repo.upsert_member(conn, actor, os.environ.get("OPENBENCH_ADMIN_NAME", "Admin"), "admin")
            conn.commit()
    finally:
        conn.close()

    shutdown = threading.Event()
    if not args.no_worker:
        assistant_worker.start_in_background(projects_http.open_connection, shutdown)

    server = OpenBenchHTTPServer((args.host, args.port), OpenBenchHandler)
    print(f"ZeroField Studio running at http://{args.host}:{args.port}/projects/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        server.server_close()
        if cleanup_pg is not None:
            cleanup_pg()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
