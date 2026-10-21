"""Take evidence bundles: the output media, the executed ComfyUI graph and how to re-run it.

A take's provenance is recorded by the comfyui adapter when the graph is submitted. Older takes fall back
to the API graph ComfyUI embeds in its saved PNG/MP4. Secrets are scrubbed here, the single exit point.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime

from openbench_data import resource_path
from project_docs import repository as repo

MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft", ".bin")
PROMPT_INPUTS = ("text", "prompt", "string_a", "string_b", "text_g", "text_l")
LOADERS = {"LoadImage": "image", "VHS_LoadVideo": "video", "LoadVideo": "file", "LoadAudio": "audio"}
APPROVED = ("Approved", "已完成")
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4",
              "video/webm": ".webm", "audio/mpeg": ".mp3", "audio/wav": ".wav"}
_SECRET_KEY = re.compile(r"api[_-]?key|secret|token|passw|authorization|credential|cookie", re.I)
_SECRET_TEXT = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
                          r"|\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{5,}"
                          r"|\b(?:sk|hf|comfyui|ghp|github_pat|xox[abp])[-_][A-Za-z0-9_-]{16,}"
                          r"|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
REDACTED = "[redacted]"


class BundleError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _secret_values():
    # Paths and sentences are not credentials; matching them would redact ordinary text.
    return [v for k, v in os.environ.items() if re.search(r"KEY|TOKEN|SECRET|PASSW", k, re.I)
            and len(v) >= 8 and not re.search(r"[\s\\/;]", v)]


def scrub(value, secrets=None):
    """Redact credential-looking keys, known key formats and the values of secret environment variables."""
    secrets = _secret_values() if secrets is None else secrets
    if isinstance(value, dict):
        return {k: REDACTED if _SECRET_KEY.search(str(k)) else scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return _SECRET_TEXT.sub(REDACTED, value)
    return value


def model_sources():
    """{basename: (folder, url)} from the Model files table in workflows/README.md."""
    try:
        text = resource_path("workflows", "README.md").read_text(encoding="utf-8")
    except OSError:
        return {}
    found = {}
    for line in text.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].lower().endswith(MODEL_SUFFIXES):
            url = re.search(r"\((https?://[^)\s]+)\)", cells[2])
            found[cells[0].lower()] = (cells[1], url.group(1) if url else None)
    return found


def embedded_graph(data, mime):
    """The API graph ComfyUI's SaveImage/SaveVideo write into the file (PNG text chunk / MP4 metadata)."""
    raw = None
    if mime == "image/png":
        try:
            from PIL import Image
            raw = Image.open(io.BytesIO(data)).info.get("prompt")
        except Exception:
            return None
    elif mime in ("video/mp4", "video/quicktime"):
        # ilst value atoms: size, "data", type 1 (UTF-8), locale 0, then the JSON text.
        for match in re.finditer(rb"(....)data\x00\x00\x00\x01\x00\x00\x00\x00(?=\{)", data, re.S):
            size = int.from_bytes(match.group(1), "big")
            try:
                candidate = json.loads(data[match.end():match.start() + size].decode("utf-8"))
            except ValueError:
                continue
            if _is_graph(candidate):
                return candidate
    try:
        graph = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return graph if _is_graph(graph) else None


def _is_graph(value):
    return isinstance(value, dict) and value and all(isinstance(n, dict) and "class_type" in n for n in value.values())


def _producer(conn, slug, url):
    with conn.cursor() as cur:
        cur.execute("""SELECT t.id::text, t.node_id, t.status, t.output, t.created_at, t.updated_at, r.tab_key, l.name
                       FROM projectops.limb_task t JOIN projectops.flow_run r ON r.id = t.run_id
                       LEFT JOIN projectops.agent_limb l ON l.id = t.limb_id
                       WHERE t.project_slug = %s AND t.output->>'asset_url' = %s
                       ORDER BY (t.output ? 'provenance') DESC, t.updated_at DESC LIMIT 1""", (slug, url))
        row = cur.fetchone()
    if not row:
        return None
    output = row[3] if isinstance(row[3], dict) else json.loads(row[3])
    return {"task_id": row[0], "node_id": row[1], "status": row[2], "output": output, "queued_at": repo._iso(row[4]),
            "completed_at": repo._iso(row[5]), "pipeline": row[6], "worker": row[7]}


def _sheet_rows(conn, slug):
    from project_docs.story_openapi import table_rows
    titles = {t["key"]: t["title"] for t in repo.list_tabs(conn, slug) if t["surface_type"] == "sheet"}
    return [dict(row, tabTitle=titles[key]) for key in titles for row in table_rows(conn, slug, key)]


def _shot(rows, url):
    for row in rows:
        for index, value in enumerate(row["cells"]):
            if url in str(value):
                return {"tab": row["tabKey"], "tab_title": row["tabTitle"], "row_id": row["rid"],
                        "label": str(row["cells"][0]), "column": row["headers"][index] if index < len(row["headers"]) else str(index),
                        "status": next((str(v) for h, v in zip(row["headers"], row["cells"]) if h.strip().lower() in ("status", "狀態")), None)}
    return None


def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")[:48] or "take"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _take_files(conn, slug, asset_id, rows, sources, secrets):
    """[(relative path, bytes)] and the take.json dict for one generated asset."""
    url = f"/projects/api/{slug}/assets/{asset_id}"
    found = repo.get_asset(conn, slug, asset_id)
    if not found:
        raise BundleError(404, "Media not found.")
    mime, data = found
    producer = _producer(conn, slug, url)
    recorded = (producer or {}).get("output", {}).get("provenance") if producer else None
    graph, source = None, "not_recorded"
    if isinstance(recorded, dict) and _is_graph(recorded.get("workflow")):
        graph, source = recorded["workflow"], "recorded_at_submit"
    else:
        recorded = {}
        graph = embedded_graph(data, mime)
        source = "embedded_in_output" if graph else source
    if not producer and not graph:
        raise BundleError(404, "This media has no generation record.")
    graph = scrub(graph or {}, secrets)
    output_name = "output" + EXTENSIONS.get(mime, ".bin")
    files = [(output_name, data)]

    inputs = []
    uploads = {u.get("name"): u for u in recorded.get("inputs", []) if isinstance(u, dict)}
    for node_id, node in graph.items():
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, str) and (value in uploads or LOADERS.get(node.get("class_type")) == name):
                upload = uploads.get(value, {})
                item = {"node": node_id, "class_type": node.get("class_type"), "input": name, "graph_value": value,
                        "sha256": upload.get("sha256"), "content_type": upload.get("content_type"), "bytes": upload.get("bytes")}
                stored = repo.get_asset(conn, slug, "pa_" + upload["sha256"][:32]) if upload.get("sha256") else None
                if stored and _hash(stored[1]) == upload["sha256"]:
                    name = _slug(value.rsplit("/", 1)[-1])
                    item["asset_id"] = "pa_" + upload["sha256"][:32]
                    item["file"] = "inputs/" + name + ("" if "." in name else EXTENSIONS.get(stored[0], ""))
                    if item["file"] not in {path for path, _ in files}:  # one upload may feed several nodes
                        files.append((item["file"], stored[1]))
                inputs.append(item)
    models = []
    for node_id, node in graph.items():
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, str) and value.lower().endswith(MODEL_SUFFIXES):
                base = re.split(r"[\\/]", value)[-1].lower()
                folder, link = sources.get(base, (None, None))
                models.append({"file": value, "node": node_id, "class_type": node.get("class_type"), "input": name,
                               "folder": folder, "source": link or "not listed in workflows/README.md"})
    prompts = [{"node": n, "class_type": node.get("class_type"), "input": k, "text": v} for n, node in graph.items()
               for k, v in (node.get("inputs") or {}).items() if k in PROMPT_INPUTS and isinstance(v, str) and v.strip()]
    seeds = [{"node": n, "input": k, "value": v} for n, node in graph.items()
             for k, v in (node.get("inputs") or {}).items() if k in ("seed", "noise_seed") and type(v) is int]
    started, finished = recorded.get("started_at"), recorded.get("finished_at")
    seconds = None
    if started and finished:
        seconds = round((datetime.fromisoformat(finished.replace("Z", "+00:00")) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds(), 3)
    take = {
        "schema": "zerofield.take/1",
        "project": slug,
        "shot": _shot(rows, url),
        "output": {"file": output_name, "asset_id": asset_id, "content_type": mime, "bytes": len(data), "sha256": _hash(data)},
        "provenance": source,
        "workflow": "workflow.json" if graph else None,
        "workflow_file": recorded.get("workflow_file"), "card_id": recorded.get("card_id"),
        "prompt": prompts,
        "seed": seeds[0]["value"] if len({s["value"] for s in seeds}) == 1 else None,
        "seeds": seeds,
        "inputs": inputs,
        "models": models,
        "platform": {"platform": recorded.get("platform"), "endpoint": recorded.get("endpoint"),
                     "comfyui_version": recorded.get("comfyui_version"), "comfy_sdk_version": recorded.get("comfy_sdk_version"),
                     "comfy_prompt_id": recorded.get("prompt_id"), "worker": (producer or {}).get("worker")},
        "timing": {"queued_at": (producer or {}).get("queued_at"), "submitted_at": started, "finished_at": finished,
                   "render_seconds": seconds, "completed_at": (producer or {}).get("completed_at")},
        "pipeline": {k: (producer or {}).get(k) for k in ("pipeline", "node_id", "task_id", "status")},
        **({"output_trimmed_to_sec": recorded["output_trimmed_to_sec"]} if "output_trimmed_to_sec" in recorded else {}),
    }
    take = scrub(take, secrets)
    if graph:
        files.append(("workflow.json", json.dumps(graph, ensure_ascii=False, indent=2).encode()))
    files.append(("take.json", json.dumps(take, ensure_ascii=False, indent=2).encode()))
    files.append(("README.md", scrub(_readme(take), secrets).encode()))
    files.append(("checksums.sha256", "".join(f"{_hash(b)}  {p}\n" for p, b in files).encode()))
    return files, take


def _readme(take):
    shot = take["shot"] or {}
    title = " · ".join(str(v) for v in (shot.get("label"), shot.get("column")) if v) or take["output"]["asset_id"]
    origin = {"recorded_at_submit": "recorded by ZeroField when the graph was submitted to ComfyUI",
              "embedded_in_output": f"recovered from the API graph ComfyUI embedded in {take['output']['file']} (this take predates submit-time recording; input hashes, platform and timing were not recorded)",
              "not_recorded": "not recorded for this take"}[take["provenance"]]
    models = "\n".join(f"- `{m['file']}` → models/{m['folder'] or '?'} — {m['source']}" for m in take["models"]) or "- none found in the graph"
    inputs = "\n".join(f"- node {i['node']}.{i['input']}: `{i['graph_value']}`" + (f" → `{i['file']}` (sha256 {i['sha256']})" if i.get("file") else " (file not included)")
                       for i in take["inputs"]) or "- none"
    return f"""# Take bundle — {title}

Generated by ZeroField Studio for project `{take['project']}`, asset `{take['output']['asset_id']}`.

## Files

- `{take['output']['file']}` — the take exactly as stored in ZeroField.
- `workflow.json` — the ComfyUI API graph that produced it, {origin}.
- `take.json` — prompt, seed, inputs with SHA-256, models with sources, platform, ComfyUI version and timing.
- `inputs/` — the media uploaded into the graph.
- `checksums.sha256` — SHA-256 of every file above.

Verify the files: `sha256sum -c checksums.sha256` (PowerShell: `Get-FileHash -Algorithm SHA256 <file>`).

## Models

{models}

## Inputs

{inputs}

## Re-run it through the Comfy SDK

1. Put the models above into your ComfyUI `models/` folders and start ComfyUI (ComfyUI {take['platform']['comfyui_version'] or 'version: see take.json'}).
2. `pip install "comfy-sdk>=0.5,<0.6" "comfy-api-proxy>=0.1.6,<0.2"` and start `comfy-api-proxy` in front of it
   (it serves the SDK's v2 API on `http://127.0.0.1:8189`). For Comfy Cloud, set `COMFY_API_KEY` instead; the cloud
   deployment needs the same models and nodes.
3. Run this next to `workflow.json`:

```python
import json, os, time
from comfy_sdk import Comfy

os.environ.setdefault("COMFY_BASE_URL", "http://127.0.0.1:8189")  # unset for Comfy Cloud
graph, take = json.load(open("workflow.json")), json.load(open("take.json"))
sdk = Comfy(api_key=os.environ.get("COMFY_API_KEY"), client_info="zerofield-take-bundle")
for item in take["inputs"]:
    if item.get("file"):
        raw = open(item["file"], "rb").read()
        graph[item["node"]]["inputs"][item["input"]] = sdk.assets.from_bytes(
            raw, filename=os.path.basename(item["file"]), content_type=item["content_type"])
job = sdk.submit(sdk.workflows.from_json(graph))
while (state := sdk.jobs.get(job.id)).status not in ("succeeded", "failed", "cancelled", "canceled"):
    time.sleep(2)
for output in state.outputs:
    with open("rerun-" + output.name, "wb") as stream:
        output.to_stream(stream)
```

Without the SDK, copy `inputs/*` into `ComfyUI/input/` (the graph references them by these names) and POST
`{{"prompt": <workflow.json>}}` to `http://127.0.0.1:8188/prompt`.

The same graph, seed and models reproduce the take on the same ComfyUI version and GPU; results can differ
slightly across GPUs, drivers and attention kernels.
"""


def _zip(entries, secrets):
    for _, data in entries:
        if any(s.encode() in data for s in secrets):
            raise BundleError(409, "The bundle was withheld because a file contains a configured credential.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in entries:
            media = path.rsplit(".", 1)[-1] in ("mp4", "webm", "png", "jpg", "webp", "mp3")
            archive.writestr(path, data, zipfile.ZIP_STORED if media else zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def take_bundle(conn, slug, asset_id):
    """(filename, zip bytes) for one take."""
    secrets = _secret_values()
    files, take = _take_files(conn, slug, asset_id, _sheet_rows(conn, slug), model_sources(), secrets)
    label = _slug((take["shot"] or {}).get("label") or "take")
    return f"zerofield-{slug}-{label}-{asset_id}.zip", _zip(files, secrets)


def project_bundle(conn, slug):
    """(filename, zip bytes) with every generated take in Approved rows and one manifest.json."""
    if not repo.get_project(conn, slug):
        raise BundleError(404, "Production not found.")
    secrets, rows, sources = _secret_values(), _sheet_rows(conn, slug), model_sources()
    entries, takes, seen = [], [], set()
    for row in rows:
        if not any(str(v).strip() in APPROVED for v in row["cells"]):
            continue
        for value in row["cells"]:
            for asset_id in re.findall(rf"/projects/api/{re.escape(slug)}/assets/(pa_[0-9a-f]{{32}})", str(value)):
                if asset_id in seen:
                    continue
                seen.add(asset_id)
                try:
                    files, take = _take_files(conn, slug, asset_id, rows, sources, secrets)
                except BundleError:
                    continue  # uploaded sources and references are not generated takes
                folder = f"{_slug(row['tabKey'])}/{_slug(take['shot']['label'] if take['shot'] else 'take')}-{_slug((take['shot'] or {}).get('column', ''))}-{asset_id}/"
                entries += [(folder + path, data) for path, data in files]
                takes.append({"folder": folder, "shot": take["shot"], "output": take["output"], "provenance": take["provenance"],
                              "seed": take["seed"], "models": sorted({m["file"] for m in take["models"]}),
                              "platform": take["platform"], "timing": take["timing"]})
    manifest = scrub({"schema": "zerofield.takes/1", "project": slug, "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                      "selection": "generated media in sheet rows whose status is Approved", "takes": takes}, secrets)
    entries.insert(0, ("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode()))
    return f"zerofield-{slug}-approved-takes.zip", _zip(entries, secrets)
