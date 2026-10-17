"""Minimal real protocol client: echo text or upload an existing image/video/audio.

This is a local acceptance worker, not a generative model. Replace execute() with
your provider SDK/ComfyUI call. Never accept shell commands from task prompts.
"""
import argparse
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def request(base, token, path, payload=None, data=None, content_type=None):
    headers = {"Authorization": "Bearer " + token}
    if data is None:
        data = json.dumps(payload or {}).encode()
        content_type = "application/json"
    headers["Content-Type"] = content_type or "application/octet-stream"
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode(errors="replace")) from exc


def execute(task, args):
    if args.asset:
        with open(args.asset, "rb") as stream:
            data = stream.read(64 * 1024 * 1024 + 1)
        query = urllib.parse.urlencode({"task_id": task["id"], "lease_token": task["lease_token"]})
        result = request(args.url, args.token, "/projects/api/limbs/upload-cell-asset?" + query,
                         data=data, content_type=mimetypes.guess_type(args.asset)[0])
        return {"asset_url": result["asset_url"]}
    return {"text": "Local example processed: " + task["input"]["prompt"][:2000]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3020")
    parser.add_argument("--token", default=os.environ.get("OPENBENCH_LIMB_TOKEN"))
    parser.add_argument("--asset", help="Upload this existing media file for each task")
    parser.add_argument("--once", action="store_true", help="Claim at most one task and exit")
    args = parser.parse_args()
    if not args.token:
        parser.error("Set OPENBENCH_LIMB_TOKEN or --token to the issued worker token")
    while True:
        claimed = request(args.url, args.token, "/projects/api/limbs/claim")
        task = claimed.get("task")
        if not task:
            if args.once:
                print("No ready tasks")
                return
            time.sleep(claimed.get("retry_after", 3))
            continue
        stopped = threading.Event()
        lease_errors = []
        lease = {"task_id": task["id"], "lease_token": task["lease_token"]}

        def heartbeat():
            while not stopped.wait(max(5, claimed["lease_seconds"] // 3)):
                try:
                    request(args.url, args.token, "/projects/api/limbs/renew", lease)
                except Exception as exc:
                    lease_errors.append(exc)
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            output = execute(task, args)
            if lease_errors:
                raise lease_errors[0]
            result = request(args.url, args.token, "/projects/api/limbs/complete", dict(lease, output=output))
            print(json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            try:
                request(args.url, args.token, "/projects/api/limbs/fail", dict(lease, error=str(exc), retryable=False))
            except Exception:
                pass
            raise
        finally:
            stopped.set()
            thread.join(timeout=1)
        if args.once:
            return


if __name__ == "__main__":
    main()
