"""Do, as the showrunner, the first-visit writes the studio would otherwise ask the demo guest to make.

The writing workspace initializes itself on a writer's first visit (POST .../writing/initialize). nginx refuses that
for the guest, so it is done here, on loopback, before nginx starts.
"""
import json
import os
import sys
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:3020"
SHOWRUNNER = "11111111-1111-4111-8111-111111111111"  # server.DEMO_MEMBERS[0]
HEADERS = {"X-OpenBench-Proxy-Secret": os.environ["OPENBENCH_HEADER_SECRET"], "X-OpenBench-Actor": SHOWRUNNER,
           "X-Writing-Expected-Actor": SHOWRUNNER,  # writing writes check it (project_docs/writing_http.py)
           "X-Requested-With": "projects", "Content-Type": "application/json"}


def call(path, body=None):
    headers = HEADERS if body is None else {**HEADERS, "Idempotency-Key": str(uuid.uuid4())}  # writing writes need one
    request = urllib.request.Request(BASE + path, method="POST" if body is not None else "GET", headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return payload.get("data", payload)


def wait_for_studio(seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=2)
            return
        except OSError:
            time.sleep(1)
    sys.exit("The studio did not come up.")


def main():
    wait_for_studio()
    episodes = call("/aivideo/open/v1/projects/pj_zerofield-showcase/episodes?limit=100")
    for episode in episodes.get("list") or episodes.get("items") or []:
        scope = f"/aivideo/open/v1/episodes/{episode['episodeId']}/writing/"
        workspace = call(scope + "workspace")
        if not workspace["structure"]["initialized"] or workspace["structure"].get("stale"):
            call(scope + "initialize", {"expectedDocHash": workspace["docHash"]})
            print(f"Initialized the writing workspace of {episode['episodeId']}", flush=True)


if __name__ == "__main__":
    main()
