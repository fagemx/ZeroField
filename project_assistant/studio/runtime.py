"""Bounded worker HTTP transport, credentials and lease-aware asset access."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import _compat as legacy

__all__ = [
    'MAX_MEDIA',
    'MAX_MATERIALS',
    'NON_TAKE_KINDS',
    'WorkerError',
    'TransientWorkerError',
    'NoRedirect',
    'fetch',
    'json_fetch',
    'configured_token',
    'Head',
]


MAX_MEDIA = 64 * 1024 * 1024


MAX_MATERIALS = 5


NON_TAKE_KINDS = frozenset({"archive", ".zip", ".tar", ".gz", ".7z"})


class WorkerError(RuntimeError):
    pass


class TransientWorkerError(WorkerError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WorkerError("HTTP redirects are disabled; configure the final endpoint")


def fetch(url, *, payload=None, data=None, token=None, mime=None, timeout=60, limit=MAX_MEDIA):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise WorkerError("Only explicit HTTP(S) endpoints are supported")
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        data, mime = json.dumps(payload, ensure_ascii=False).encode(), "application/json"
    if mime:
        headers["Content-Type"] = mime
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise WorkerError("Response exceeds configured size limit")
            return body, response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        # Provider errors can contain credentials or signed URLs; report status only.
        error = TransientWorkerError if exc.code in (408, 429) or exc.code >= 500 else WorkerError
        raise error(f"HTTP {exc.code} from configured endpoint") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TransientWorkerError("Configured endpoint temporarily unavailable") from None


def json_fetch(url, **kwargs):
    data, _ = legacy.fetch(url, limit=4 * 1024 * 1024, **kwargs)
    try:
        return json.loads(data)
    except ValueError:
        raise WorkerError("Endpoint returned invalid JSON") from None


def configured_token(config):
    name = config.get("api_key_env")
    if name and not os.environ.get(name):
        raise WorkerError(f"Required environment variable is missing: {name}")
    return os.environ.get(name) if name else None


class Head:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def action(self, name, payload=None):
        return legacy.json_fetch(self.base + "/projects/api/limbs/" + name, payload=payload or {}, token=self.token)

    def upload(self, task, data, mime, filename=None):
        if getattr(self, "lease_lost", lambda: False)():
            raise WorkerError("Lease was lost; output cannot be uploaded")
        if len(data) > legacy.MAX_MEDIA:
            raise WorkerError("Output exceeds the 64 MB asset limit")
        lease={"task_id": task["id"], "lease_token": task["lease_token"]}
        if task.get('dispatch_handle'):
            lease['dispatch_handle']=task['dispatch_handle']
        query = urllib.parse.urlencode(lease)
        prefix='orchestration/' if task.get('dispatch_handle') else ''
        result = legacy.json_fetch(self.base + "/projects/api/limbs/"+prefix+"upload-cell-asset?" + query,
                            data=data, mime=mime, token=self.token)
        url = result["asset_url"]
        identifier = url.rsplit("/", 1)[-1]
        return {"asset_url": url, "content_type": result["content_type"],
                **({"asset_id": identifier} if re.fullmatch(r"pa_[0-9a-f]{32}", identifier) else {})}

    def asset(self, task, url):
        prefix = f"/projects/api/{task['project_slug']}/assets/"
        if not isinstance(url, str) or not url.startswith(prefix) or not re.fullmatch(r"pa_[0-9a-f]{32}", url[len(prefix):]):
            raise WorkerError("Media input must be an asset in the task project")
        return legacy.fetch(self.base + url, token=self.token)
