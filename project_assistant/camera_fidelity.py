"""Camera fidelity: does a take move its camera the way its shot's previs does?

Per frame step, corners tracked with pyramidal Lucas-Kanade on a downscaled frame give point pairs; a RANSAC similarity
fit (estimateAffinePartial2D) gives the image-space camera motion: pan and tilt (fraction of frame width) and zoom (log
scale). Moving actors are outliers to the fit. The score correlates the cumulative paths per component, weighted by how
far the previs moves that component; a component the previs holds still scores by how still the take keeps it. The
score saturates near 1 once the path shape matches, so travel (the take's move as a fraction of the previs', taken
where the previs moves furthest) is the number that tells takes apart. Ported from research/motion_lab/fidelity.py;
see docs/research/2026-10-20-motion-control-lab.md.

A video take landing in a row with a Previs is measured on one background thread, never in the worker or the request.
Results are kept per (previs, take) asset pair in story_record: both ids are content hashes, so a pair never changes.
Failures stay in memory only, so a restart (for example after installing OpenCV) measures again.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
import threading

from project_docs import repository as repo

STILL = 0.03  # a component that travels less than this (frame widths / log zoom) over the shot counts as held
MIN_TRAVEL = 0.1  # a travel ratio over a smaller previs move is mostly tracking noise, so none is reported
COMPONENTS = (("pan", 0), ("tilt", 1), ("zoom", 2))
KIND = "camera_fidelity"
PREVIS = re.compile(r"previs|blockout", re.I)
ASSET = re.compile(r"/projects/api/[a-z0-9-]+/assets/(pa_[0-9a-f]{32})")

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera-fidelity")
_LOCK = threading.Lock()
_PENDING: set = set()
_FAILED: dict = {}


def motion(path, width=320):
    import cv2
    import numpy as np
    cap, prev, steps = cv2.VideoCapture(str(path)), None, []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(cv2.resize(frame, (width, int(frame.shape[0] * width / frame.shape[1]))), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            # Track textured corners only: flat fog, sky and grey walls have no measurable flow and would vote for "no motion".
            src = cv2.goodFeaturesToTrack(prev, maxCorners=500, qualityLevel=0.005, minDistance=6)
            m = None
            if src is not None and len(src) >= 12:
                dst, ok, _ = cv2.calcOpticalFlowPyrLK(prev, gray, src, None, winSize=(21, 21), maxLevel=4)
                good = ok.ravel() == 1
                if good.sum() >= 12:
                    m, _ = cv2.estimateAffinePartial2D(src[good], dst[good], method=cv2.RANSAC, ransacReprojThreshold=1.5)
            if m is None:
                steps.append((0.0, 0.0, 0.0))
            else:
                scale = float(np.hypot(m[0, 0], m[1, 0]))
                cx, cy = gray.shape[1] / 2, gray.shape[0] / 2  # translation of the frame centre, so zoom does not read as pan
                tx = m[0, 0] * cx - m[1, 0] * cy + m[0, 2] - cx
                ty = m[1, 0] * cx + m[0, 0] * cy + m[1, 2] - cy
                steps.append((tx / width, ty / width, np.log(max(scale, 1e-6))))
        prev = gray
    cap.release()
    return np.array(steps)


def score(previs, take):
    """Compare the cumulative camera paths (shape and direction, not per-frame speed: the model keeps the move, not its
    exact easing). Frames align by index; the lanes render the take at the previs' length."""
    import numpy as np
    a, b = motion(previs), motion(take)
    n = min(len(a), len(b))
    if n < 8:
        raise ValueError("Both clips need at least 9 decodable frames.")
    out, parts = {"frames": n + 1}, []
    for name, i in COMPONENTS:
        x, y = np.cumsum(a[:n, i]), np.cumsum(b[:n, i])
        peak = int(np.abs(x).argmax())
        reach = abs(float(x[peak]))
        if reach < STILL:
            s, weight = max(0.0, 1 - max(0.0, float(np.abs(y).max()) - STILL) / (3 * STILL)), STILL
        else:
            s = float(np.corrcoef(x, y)[0, 1]) if x.std() > 1e-9 and y.std() > 1e-9 else 0.0
            weight = reach
        out[name] = {"score": round(s, 2), "previs": round(float(x[peak]), 3), "take": round(float(y[peak]), 3),
                     "travel": round(float(y[peak] / x[peak]), 2) if reach >= MIN_TRAVEL else None}
        parts.append((s, weight))
    out["score"] = round(sum(s * w for s, w in parts) / sum(w for _, w in parts), 2)
    return out


def previs_asset(headers, cells):
    """The row's Previs asset id, or None."""
    for header, cell in zip(headers, cells):
        if PREVIS.search(str(header)):
            found = ASSET.search(str(cell))
            return found[1] if found else None
    return None


def _record_id(slug, previs_id, take_id):
    return f"{KIND}:{slug}:{previs_id}:{take_id}"


def status(conn, slug, previs_id, take_id):
    """(http status, payload): the stored result, a failure, or pending after queueing the measurement."""
    from project_docs.story_openapi import record
    found = record(conn, _record_id(slug, previs_id, take_id), required=False)
    if found:
        return 200, found
    key = (slug, previs_id, take_id)
    if key in _FAILED:
        return 200, {"status": "failed", "error": _FAILED[key]}
    metas = [repo.get_asset_meta(conn, slug, asset_id) for asset_id in (previs_id, take_id)]
    if not all(meta and meta[0].startswith("video/") for meta in metas):
        return 404, {"error": "Camera fidelity compares a previs video with a video take from this production."}
    schedule(*key)
    return 200, {"status": "pending"}


def schedule(slug, previs_id, take_id):
    key = (slug, previs_id, take_id)
    with _LOCK:
        if key in _PENDING:
            return
        _PENDING.add(key)
    _POOL.submit(_measure, key)


def _measure(key):
    from project_docs import http
    from project_docs.story_openapi import store
    slug, previs_id, take_id = key
    try:
        with http.open_connection() as conn:
            clips = [repo.get_asset(conn, slug, asset_id) for asset_id in (previs_id, take_id)]
        if not all(clip and clip[0].startswith("video/") for clip in clips):
            raise ValueError("The previs or the take is no longer a video in this production.")
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, (mime, data) in zip(("previs", "take"), clips):
                paths.append(Path(folder) / f"{name}.{mime.split('/', 1)[1]}")
                paths[-1].write_bytes(data)
            result = dict(score(*paths), status="done")
        result.update(previs=previs_id, take=take_id, measured_at=datetime.now(timezone.utc).isoformat())
        with http.open_connection() as conn:
            store(conn, _record_id(*key), KIND, result, slug)
    except Exception as exc:  # noqa: BLE001 - a take stays usable whatever happens here
        message = "OpenCV and NumPy are required to measure camera fidelity." if isinstance(exc, ImportError) \
            else f"{type(exc).__name__}: {exc}"[:300]
        print(f"camera fidelity: {slug} {previs_id} -> {take_id} failed: {message}", flush=True)
        with _LOCK:
            _FAILED[key] = message
    finally:
        with _LOCK:
            _PENDING.discard(key)
