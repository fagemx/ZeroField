"""Re-render a 3D Stage previs headless with the product's own scene.js / webm.js, from the plan stored in the WebM.

usage: python stage_render.py PREVIS.webm|PLAN.json OUT.webm|OUT.json [matte|skeleton|pose]
A PLAN.json renders a plan written by hand or by a lab script (performance keys, poses, cast) instead of a stored one.
"matte" renders every cast member white on black (scene.js matte) for guide attention masks.
"skeleton" renders the pose skeleton pass Render previs writes for the Layout Render (ui/src/previs/skeleton.js).
"pose" writes OUT.json instead of a video: per frame, every cast member's OpenPose keypoints in pixels (18 body points
[x, y, visible], 21 per hand), the same points the skeleton draws.
"""
import base64, json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PAGE = """<!doctype html><body style="margin:0"><script type="importmap">{"imports":{"three":"/ui/node_modules/three/build/three.module.js"}}</script>
<script type="module">
import * as THREE from 'three';
import { buildStage, prepareRenderer } from '/ui/src/previs/scene.js';
import { framesOf, WIDTH, HEIGHT, FPS } from '/ui/src/previs/plan.js';
import { encodeCanvas, planFromWebM } from '/ui/src/previs/webm.js';
import { poseKeypoints, drawSkeleton } from '/ui/src/previs/skeleton.js';
const renderer = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
renderer.setPixelRatio(1); renderer.setSize(WIDTH, HEIGHT, false); document.body.appendChild(renderer.domElement);
window.render = async (b64, matte, json) => {
  const plan = json ? JSON.parse(json) : planFromWebM(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
  const stage = buildStage(plan); stage.roof(true);
  if (matte) stage.matte(true);  // every cast member white on black (scene.js tags them), whatever their coat
  const blob = await encodeCanvas(renderer.domElement, framesOf(plan), FPS, f => { stage.frame(f, plan); renderer.render(stage.scene, stage.camera); }, null, plan);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let s = ''; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
// Pose keypoints per frame (JSON), or the pose skeleton video the product renders (ui/src/previs/skeleton.js).
window.keypoints = async json => {
  const plan = JSON.parse(json), stage = buildStage(plan), out = [];
  for (let f = 0; f < framesOf(plan); f++) { stage.frame(f, plan); out.push(poseKeypoints(stage.scene, stage.camera)); }
  return JSON.stringify(out);
};
window.skeleton = async json => {
  const plan = JSON.parse(json), stage = buildStage(plan), canvas = document.createElement('canvas');
  canvas.width = WIDTH; canvas.height = HEIGHT; const ctx = canvas.getContext('2d');
  const blob = await encodeCanvas(canvas, framesOf(plan), FPS, f => { stage.frame(f, plan); drawSkeleton(ctx, poseKeypoints(stage.scene, stage.camera)); }, null, null);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let s = ''; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
window.ready = true;
</script></body>"""


def plan_of(webm):
    head = Path(webm).read_bytes()[:8192].decode("latin-1")
    return json.JSONDecoder().raw_decode(head, head.index("zf-plan:") + len("zf-plan:"))[0]


def main(src, dest, mode=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=d3d11", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1280, "height": 704})

        def serve(route):
            path = route.request.url.split("http://localhost:9", 1)[1].split("?")[0]
            if path == "/":
                return route.fulfill(body=PAGE, content_type="text/html")
            return route.fulfill(path=str(ROOT / path.lstrip("/")), content_type="text/javascript")

        page.route("http://localhost:9/**", serve)
        page.goto("http://localhost:9/")
        page.wait_for_function("window.ready === true", timeout=60000)
        json_plan = Path(src).read_text(encoding="utf-8") if str(src).endswith(".json") else None
        head = "" if json_plan else base64.b64encode(Path(src).read_bytes()[:8192]).decode()
        if mode == "pose":
            Path(dest).write_text(page.evaluate("j => window.keypoints(j)", json_plan or json.dumps(plan_of(src))), encoding="utf-8")
        elif mode == "skeleton":
            Path(dest).write_bytes(base64.b64decode(page.evaluate("j => window.skeleton(j)", json_plan or json.dumps(plan_of(src)))))
        else:
            Path(dest).write_bytes(base64.b64decode(page.evaluate("([b, m, j]) => window.render(b, m, j)", [head, mode == "matte", json_plan])))
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print("ok", sys.argv[2])
