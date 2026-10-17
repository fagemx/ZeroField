"""Small, fail-closed authentication for local, token and reverse-proxy installs."""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

SESSION_SECONDS = 12 * 60 * 60


class AuthError(ValueError):
    pass


def config(env=None):
    env = os.environ if env is None else env
    mode = env.get("OPENBENCH_AUTH_MODE", "dev")
    if mode not in ("dev", "token", "header"):
        raise AuthError("OPENBENCH_AUTH_MODE must be dev, token or header")
    try:
        tokens = json.loads(env.get("OPENBENCH_TOKENS", "{}"))
        if not isinstance(tokens, dict):
            raise ValueError()
        for token, actor in tokens.items():
            if len(token) < 24 or str(uuid.UUID(actor)) != actor:
                raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AuthError("OPENBENCH_TOKENS must map tokens of at least 24 characters to member UUIDs") from None
    proxy_secret = env.get("OPENBENCH_HEADER_SECRET", "")
    if mode == "token" and not tokens:
        raise AuthError("Token mode requires OPENBENCH_TOKENS")
    if mode == "header" and len(proxy_secret) < 24:
        raise AuthError("Header mode requires OPENBENCH_HEADER_SECRET of at least 24 characters")
    key = env.get("OPENBENCH_SESSION_SECRET") or json.dumps(tokens, sort_keys=True)
    return {"mode": mode, "tokens": tokens, "proxy_secret": proxy_secret, "key": hashlib.sha256(key.encode()).digest()}


def token_actor(token, cfg):
    for expected, actor in cfg["tokens"].items():
        if hmac.compare_digest(str(token).encode(), expected.encode()):
            return actor
    return None


def issue_session(actor, cfg, now=None):
    payload = base64.urlsafe_b64encode(json.dumps([actor, int(time.time() if now is None else now)]).encode()).decode().rstrip("=")
    signature = hmac.new(cfg["key"], payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def session_actor(value, cfg, now=None):
    try:
        payload, signature = value.split(".")
        expected = hmac.new(cfg["key"], payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        actor, created = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        age = int(time.time() if now is None else now) - created
        return actor if 0 <= age < SESSION_SECONDS and actor in cfg["tokens"].values() else None
    except (ValueError, TypeError, KeyError):
        return None


def resolve(headers, cookies, cfg, default_actor=None):
    if cfg["mode"] == "dev":
        return headers.get("X-OpenBench-Actor") or cookies.get("openbench_actor") or default_actor
    if cfg["mode"] == "header":
        supplied = headers.get("X-OpenBench-Proxy-Secret", "")
        return headers.get("X-OpenBench-Actor") if hmac.compare_digest(supplied, cfg["proxy_secret"]) else None
    bearer = headers.get("Authorization", "")
    if bearer.startswith("Bearer "):
        return token_actor(bearer[7:], cfg)
    return session_actor(cookies.get("openbench_session", ""), cfg)
